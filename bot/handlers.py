import logging
from datetime import datetime, date as _date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    filters,
)
from services.transcribe import transcribe_audio, download_telegram_file
from services.extract import extract_expenses, extract_expense_from_image, apply_edit, Expense
from services.sheets import append_expense, append_income, get_effective_budget, delete_row
from services.storage import get_users
from services.config_store import set as cfg_set

logger = logging.getLogger(__name__)

WAITING_CONFIRMATION = 1
WAITING_EDIT = 2
_PENDING_EXPENSES = "pending_expenses"  # list[Expense]
_PENDING_IDX = "pending_idx"            # int
_LAST_SAVED = "last_saved"              # {"row": int, "sheet": str, "expense": Expense}


def _is_authorized(update: Update) -> bool:
    return update.effective_user.id in get_users()


def _entry_preview(expense: Expense, idx: int = 0, total: int = 1) -> str:
    prefix = f"*{'Entrata' if expense.type == 'entrata' else 'Spesa'} {idx + 1} di {total}:*\n\n" if total > 1 else ""
    if expense.type == "entrata":
        return (
            f"{prefix}💰 *Ho capito questa entrata:*\n\n"
            f"💶 Importo: *€{expense.amount:.2f}*\n"
            f"📋 Descrizione: {expense.description}\n"
            f"📅 Data: {expense.date}\n\n"
            f"Confermo?"
        )
    return (
        f"{prefix}📝 *Ho capito questa spesa:*\n\n"
        f"💶 Importo: *€{expense.amount:.2f}*\n"
        f"🏷️ Categoria: *{expense.category}*\n"
        f"📋 Descrizione: {expense.description}\n"
        f"📅 Data: {expense.date}\n\n"
        f"Confermo?"
    )


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Sì", callback_data="confirm"),
            InlineKeyboardButton("✏️ Modifica", callback_data="edit"),
            InlineKeyboardButton("❌ No", callback_data="cancel"),
        ]
    ])


def _current_expense(context: ContextTypes.DEFAULT_TYPE) -> Expense | None:
    expenses = context.user_data.get(_PENDING_EXPENSES, [])
    idx = context.user_data.get(_PENDING_IDX, 0)
    return expenses[idx] if 0 <= idx < len(expenses) else None


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    await update.message.reply_text(
        "👋 Ciao! Scrivi liberamente cosa hai speso o cosa vuoi fare.\n\n"
        "Esempio: *ho speso 12 euro al bar*\n"
        "Oppure: *quanto ho speso questo mese?*\n\n"
        "Scrivi /info per una guida completa.",
        parse_mode="Markdown"
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        return ConversationHandler.END

    await update.message.reply_text("🎙️ Sto trascrivendo...")

    voice = update.message.voice
    tg_file = await voice.get_file()
    audio_bytes = await download_telegram_file(tg_file.file_path)

    text = await transcribe_audio(audio_bytes, filename="audio.ogg")
    logger.info("Trascrizione: %s", text)

    return await _dispatch_ai(update, context, text)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        return ConversationHandler.END

    text = update.message.text.strip()
    if text.startswith("/"):
        return ConversationHandler.END

    return await _dispatch_ai(update, context, text)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        return ConversationHandler.END

    await update.message.reply_text("📸 Sto analizzando lo scontrino...")

    photo = update.message.photo[-1]
    tg_file = await photo.get_file()
    image_bytes = await download_telegram_file(tg_file.file_path)

    expenses = extract_expense_from_image(image_bytes)
    return await _process_expenses(update, context, expenses)


async def _dispatch_ai(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> int:
    from services.ai_router import classify_intent
    from services.recurring import load as load_recurring, add as add_recurring, remove as remove_recurring

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    result = classify_intent(text)
    intent = result.get("intent", "non_capito")
    params = result.get("params", {})
    risposta = result.get("risposta", "")

    # --- Registra spesa/entrata ---
    if intent == "registra":
        return await _process_text_raw(update, context, text)

    # --- Riepilogo mensile ---
    if intent == "riepilogo":
        await _send_riepilogo(update, context)
        return ConversationHandler.END

    # --- Aggiungi costo fisso ---
    if intent == "aggiungi_ricorrente":
        amount = params.get("amount")
        description = str(params.get("description", "")).strip()
        interval = int(params.get("interval_months", 1))
        if not amount or not description:
            await update.message.reply_text(
                "🤔 Non ho capito bene. Dimmi importo, nome e frequenza.\n"
                "Esempio: _aggiungi iCloud 0.99 ogni mese_",
                parse_mode="Markdown",
            )
            return ConversationHandler.END

        start_date = None
        raw_start = params.get("start_date")
        if raw_start:
            try:
                start_date = _date.fromisoformat(raw_start)
            except ValueError:
                pass

        item = add_recurring(float(amount), description, interval, start_date)
        interval_str = f"ogni {interval} mesi" if interval > 1 else "ogni mese"

        # If next_due is today or earlier, auto-log the current cycle immediately
        auto_logged = False
        if _date.fromisoformat(item.next_due) <= _date.today():
            try:
                from services.sheets import append_expense
                from services.extract import Expense as _Expense
                from services.recurring import advance as _advance, update_item as _update_item
                exp = _Expense(date=item.next_due, amount=item.amount,
                               category="Costi Fissi", description=item.description)
                append_expense(exp)
                _update_item(_advance(item))
                # Reload item to get updated next_due
                from services.recurring import load as _load
                item = next((i for i in _load() if i.id == item.id), item)
                auto_logged = True
            except Exception as e:
                logger.error("Errore auto-log ricorrente: %s", e)

        msg = (
            f"✅ Costo fisso aggiunto:\n"
            f"• €{float(amount):.2f} — {description} ({interval_str})\n"
        )
        if auto_logged:
            msg += f"• ✅ Pagamento del ciclo corrente registrato automaticamente in Sheets\n"
        msg += f"• Prossima scadenza: {item.next_due}"
        await update.message.reply_text(msg)
        return ConversationHandler.END

    # --- Lista costi fissi ---
    if intent == "lista_ricorrente":
        items = load_recurring()
        if not items:
            await update.message.reply_text(
                "Non hai costi fissi configurati.\n\n"
                "Per aggiungerne uno scrivi ad esempio:\n"
                "_aggiungi Spotify 9.99 ogni 4 mesi_",
                parse_mode="Markdown",
            )
        else:
            lines = ["🔄 *Costi fissi ricorrenti:*\n"]
            for item in items:
                interval_str = f"ogni {item.interval_months} mesi" if item.interval_months > 1 else "mensile"
                lines.append(f"• €{item.amount:.2f} — {item.description} ({interval_str})\n  Prossima: {item.next_due}")
            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return ConversationHandler.END

    # --- Rimuovi costo fisso ---
    if intent == "rimuovi_ricorrente":
        desc_query = str(params.get("description", "")).lower().strip()
        items = load_recurring()
        matched = [i for i in items if desc_query in i.description.lower()]
        if not matched:
            await update.message.reply_text(f"Non ho trovato nessun costo fisso con il nome '{params.get('description', '')}'.")
        elif len(matched) == 1:
            remove_recurring(matched[0].id)
            await update.message.reply_text(f"✅ Rimosso: €{matched[0].amount:.2f} — {matched[0].description}")
        else:
            lines = ["Ho trovato più voci simili. Scrivi il nome esatto di quella da rimuovere:\n"]
            for item in matched:
                lines.append(f"• {item.description} — €{item.amount:.2f}")
            await update.message.reply_text("\n".join(lines))
        return ConversationHandler.END

    # --- Imposta budget ---
    if intent == "imposta_budget":
        amount = params.get("amount")
        if not amount or float(amount) <= 0:
            await update.message.reply_text("Non ho capito l'importo. Dimmi quanto vuoi impostare come budget mensile.")
        else:
            cfg_set("budget", float(amount))
            await update.message.reply_text(f"✅ Budget mensile impostato a *€{float(amount):.0f}*", parse_mode="Markdown")
        return ConversationHandler.END

    # --- Info/tutorial ---
    if intent == "info":
        from bot.admin import _INFO_TEXT
        await update.message.reply_text(_INFO_TEXT, parse_mode="MarkdownV2")
        return ConversationHandler.END

    # --- Annulla ultima voce ---
    if intent == "annulla_ultima":
        last = context.user_data.get(_LAST_SAVED)
        if not last or last.get("row", -1) <= 0:
            await update.message.reply_text(
                "Non ho nessuna voce recente da annullare.\n"
                "Posso annullare solo la spesa/entrata appena registrata in questa sessione."
            )
        else:
            exp = last["expense"]
            ok = delete_row(last["sheet"], last["row"])
            context.user_data.pop(_LAST_SAVED, None)
            if ok:
                label = "entrata" if exp.type == "entrata" else "spesa"
                await update.message.reply_text(
                    f"✅ {label.capitalize()} annullata: €{exp.amount:.2f} — {exp.description}\n\n"
                    f"Puoi reinserirla quando vuoi."
                )
            else:
                await update.message.reply_text("⚠️ Non sono riuscito ad annullare la voce. Prova a eliminarla direttamente da Google Sheets.")
        return ConversationHandler.END

    # --- Modifica ultima voce ---
    if intent == "modifica_ultima":
        last = context.user_data.get(_LAST_SAVED)
        if not last or last.get("row", -1) <= 0:
            await update.message.reply_text(
                "Non ho nessuna voce recente da modificare.\n"
                "Posso modificare solo la spesa/entrata appena registrata."
            )
            return ConversationHandler.END

        exp: Expense = last["expense"]
        # Apply the corrections from params
        new_amount = float(params["amount"]) if "amount" in params else exp.amount
        new_category = params.get("category", exp.category)
        new_description = params.get("description", exp.description)
        corrected = Expense(
            date=exp.date,
            amount=new_amount,
            category=new_category,
            description=new_description,
            type=exp.type,
        )

        # Delete old row, then re-show as pending for confirmation
        delete_row(last["sheet"], last["row"])
        context.user_data.pop(_LAST_SAVED, None)

        context.user_data[_PENDING_EXPENSES] = [corrected]
        context.user_data[_PENDING_IDX] = 0
        await update.message.reply_text(
            "Ho annullato la voce precedente. Confermi quella corretta?",
        )
        await update.message.reply_text(
            _entry_preview(corrected),
            parse_mode="Markdown",
            reply_markup=_confirm_keyboard(),
        )
        return WAITING_CONFIRMATION

    # --- Conversazione / risposta AI ---
    if intent == "conversa" and risposta:
        await update.message.reply_text(risposta)
        return ConversationHandler.END

    # --- Impossibile ---
    if intent == "impossibile":
        motivo = params.get("motivo", "Non riesco a fare questa cosa.")
        await update.message.reply_text(f"😕 {motivo}")
        return ConversationHandler.END

    # --- Non capito ---
    domanda = params.get("domanda", "Non ho capito bene. Puoi spiegarmi meglio cosa vorresti fare?")
    await update.message.reply_text(f"🤔 {domanda}")
    return ConversationHandler.END


async def _send_riepilogo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    from services.sheets import get_monthly_summary, get_monthly_income
    from services.config_store import get as cfg_get

    today = _date.today()
    month_names = [
        "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
        "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
    ]

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")
    summary = get_monthly_summary(today.year, today.month)
    total_expenses = summary.pop("_total", 0.0)
    income = get_monthly_income(today.year, today.month)

    if total_expenses == 0 and income == 0:
        await update.message.reply_text(f"📊 Nessuna voce registrata a {month_names[today.month]}.")
        return

    lines = [f"📊 *Riepilogo {month_names[today.month]} {today.year}*\n"]
    if income > 0:
        lines.append(f"💰 Entrate: *€{income:.2f}*")
    if total_expenses > 0:
        lines.append(f"💸 Spese totali: *€{total_expenses:.2f}*")
        lines.append("")
        for cat, amount in sorted(summary.items(), key=lambda x: -x[1]):
            lines.append(f"• {cat}: €{amount:.2f}")
    if income > 0 and total_expenses > 0:
        saldo = income - total_expenses
        pct = (saldo / income * 100) if income > 0 else 0
        emoji = "✅" if saldo >= 0 else "🚨"
        lines.append(f"\n{emoji} *Saldo: €{saldo:.2f}* ({pct:.0f}% disponibile)")
    elif total_expenses > 0:
        budget = cfg_get("budget")
        if budget:
            pct = (total_expenses / budget) * 100
            lines.append(f"\n📌 Budget: €{budget:.0f} — usato {pct:.0f}%")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _process_text_raw(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> int:
    expenses = extract_expenses(text)
    return await _process_expenses(update, context, expenses)


async def _process_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE, expenses: list) -> int:
    if not expenses:
        await update.message.reply_text(
            "🤔 Non sono riuscito a capire. Prova con qualcosa tipo:\n"
            "_ho speso 25 euro al supermercato_\n"
            "_ho ricevuto 1500 euro di stipendio_",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    context.user_data[_PENDING_EXPENSES] = expenses
    context.user_data[_PENDING_IDX] = 0

    await update.message.reply_text(
        _entry_preview(expenses[0], 0, len(expenses)),
        parse_mode="Markdown",
        reply_markup=_confirm_keyboard(),
    )
    return WAITING_CONFIRMATION


async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    expenses: list = context.user_data.get(_PENDING_EXPENSES, [])
    idx: int = context.user_data.get(_PENDING_IDX, 0)
    total = len(expenses)
    expense: Expense | None = expenses[idx] if idx < total else None

    if query.data == "edit":
        hint = (
            "✏️ Cosa vuoi modificare?\n\n"
            "Scrivi ad esempio:\n"
            "• _importo 25_\n"
            "• _descrizione Stipendio maggio_\n"
            "• _data ieri_"
            if expense and expense.type == "entrata"
            else
            "✏️ Cosa vuoi modificare?\n\n"
            "Scrivi ad esempio:\n"
            "• _importo 25_\n"
            "• _categoria Trasporti_\n"
            "• _descrizione Spesa Lidl_\n"
            "• _data ieri_"
        )
        await query.edit_message_text(hint, parse_mode="Markdown")
        return WAITING_EDIT

    if query.data == "confirm" and expense:
        try:
            is_income = expense.type == "entrata"
            if is_income:
                row_num = append_income(expense)
                sheet_name = "Entrate"
            else:
                row_num = append_expense(expense)
                sheet_name = "Spese"
                cfg_set("last_expense_date", expense.date)

            # Store for possible undo/edit
            context.user_data[_LAST_SAVED] = {"row": row_num, "sheet": sheet_name, "expense": expense}

            budget_msg = ""
            saldo_msg = ""
            if idx + 1 >= total:
                parsed = datetime.strptime(expense.date, "%Y-%m-%d")
                if is_income:
                    budget_msg = f"\n\n📌 Budget di {parsed.strftime('%B')} aggiornato a *€{expense.amount:.2f}*"
                else:
                    from services.sheets import get_monthly_summary
                    budget = get_effective_budget(parsed.year, parsed.month)
                    if budget:
                        summary = get_monthly_summary(parsed.year, parsed.month)
                        t = summary.get("_total", 0.0)
                        pct = (t / budget) * 100
                        if pct >= 100:
                            budget_msg = f"\n\n🚨 *Budget superato!* Hai speso €{t:.2f} su €{budget:.0f} ({pct:.0f}%)"
                        elif pct >= 80:
                            budget_msg = f"\n\n⚠️ Attenzione: hai usato l'*{pct:.0f}%* del budget (€{t:.2f} / €{budget:.0f})"
                    try:
                        from services.sheets import get_cumulative_balance
                        bal = get_cumulative_balance()
                        b = bal["balance"]
                        saldo_emoji = "✅" if b >= 0 else "⚠️"
                        saldo_msg = f"\n\n{saldo_emoji} *Saldo: €{b:.2f}*"
                    except Exception:
                        pass

            label = "Entrata" if is_income else "Spesa"
            emoji = "💰" if is_income else "✅"

            if total > 1:
                await query.edit_message_text(
                    f"{emoji} {label} {idx + 1}/{total} salvata: €{expense.amount:.2f} — {expense.description}" + budget_msg + saldo_msg,
                    parse_mode="Markdown",
                )
            else:
                detail = f"€{expense.amount:.2f} — {expense.description}" if is_income else f"€{expense.amount:.2f} — {expense.category}\n_{expense.description}_"
                await query.edit_message_text(
                    f"{emoji} *{label} salvata!*\n\n{detail}" + budget_msg + saldo_msg,
                    parse_mode="Markdown",
                )
        except Exception as e:
            logger.error("Errore salvataggio: %s", e)
            await query.edit_message_text("⚠️ Errore nel salvataggio. Riprova.")

    else:
        label = "Entrata" if (expense and expense.type == "entrata") else "Spesa"
        if total > 1:
            await query.edit_message_text(f"❌ {label} {idx + 1}/{total} annullata.")
        else:
            await query.edit_message_text("❌ Operazione annullata.")

    idx += 1
    context.user_data[_PENDING_IDX] = idx

    if idx < total:
        await query.message.reply_text(
            _entry_preview(expenses[idx], idx, total),
            parse_mode="Markdown",
            reply_markup=_confirm_keyboard(),
        )
        return WAITING_CONFIRMATION

    context.user_data.pop(_PENDING_EXPENSES, None)
    context.user_data.pop(_PENDING_IDX, None)
    return ConversationHandler.END


async def handle_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    expense = _current_expense(context)
    if not expense:
        await update.message.reply_text("❌ Nessuna voce in attesa. Inizia da capo.")
        return ConversationHandler.END

    edit_text = update.message.text.strip()
    updated = apply_edit(expense, edit_text)

    if updated is None:
        await update.message.reply_text(
            "🤔 Non ho capito la modifica. Riprova (es. 'importo 25' o 'categoria Trasporti')."
        )
        return WAITING_EDIT

    expenses = context.user_data[_PENDING_EXPENSES]
    idx = context.user_data[_PENDING_IDX]
    expenses[idx] = updated

    await update.message.reply_text(
        _entry_preview(updated, idx, len(expenses)),
        parse_mode="Markdown",
        reply_markup=_confirm_keyboard(),
    )
    return WAITING_CONFIRMATION


async def handle_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop(_PENDING_EXPENSES, None)
    context.user_data.pop(_PENDING_IDX, None)
    if update.message:
        await update.message.reply_text("⏱️ Tempo scaduto. Reinvia la voce.")
    return ConversationHandler.END


def build_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.PHOTO, handle_photo),
            MessageHandler(filters.VOICE, handle_voice),
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text),
        ],
        states={
            WAITING_CONFIRMATION: [
                CallbackQueryHandler(handle_confirmation, pattern="^(confirm|edit|cancel)$"),
            ],
            WAITING_EDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_edit_text),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
        ],
        conversation_timeout=120,
        per_message=False,
    )
