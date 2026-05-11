import logging
from datetime import datetime
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
from services.sheets import append_expense, append_income, get_effective_budget
from services.storage import get_users
from services.config_store import set as cfg_set

logger = logging.getLogger(__name__)

WAITING_CONFIRMATION = 1
WAITING_EDIT = 2
_PENDING_EXPENSES = "pending_expenses"  # list[Expense]
_PENDING_IDX = "pending_idx"            # int


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
        "👋 Ciao! Inviami un messaggio vocale, scrivi la spesa, o manda la foto di uno scontrino.\n\n"
        "Esempio: *ho speso 12 euro al bar e 50 al supermercato*\n"
        "Oppure: *ho ricevuto 1500 euro di stipendio*\n"
        "Usa /help per vedere tutti i comandi.",
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

    return await _process_text(update, context, text)


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        return ConversationHandler.END

    text = update.message.text.strip()
    if text.startswith("/"):
        return ConversationHandler.END

    return await _process_text(update, context, text)


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _is_authorized(update):
        return ConversationHandler.END

    await update.message.reply_text("📸 Sto analizzando lo scontrino...")

    photo = update.message.photo[-1]  # highest resolution
    tg_file = await photo.get_file()
    image_bytes = await download_telegram_file(tg_file.file_path)

    expenses = extract_expense_from_image(image_bytes)
    return await _process_expenses(update, context, expenses)


async def _process_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> int:
    expenses = extract_expenses(text)
    return await _process_expenses(update, context, expenses)


async def _process_expenses(update: Update, context: ContextTypes.DEFAULT_TYPE, expenses: list) -> int:
    if not expenses:
        await update.message.reply_text(
            "❓ Non sono riuscito a capire la voce. Riprova con un messaggio più chiaro.\n"
            "Esempio spesa: *ho speso 25 euro al supermercato*\n"
            "Esempio entrata: *ho ricevuto 1500 euro di stipendio*",
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
        if expense and expense.type == "entrata":
            await query.edit_message_text(
                "✏️ Cosa vuoi modificare?\n\n"
                "Scrivi ad esempio:\n"
                "• _importo 1500_\n"
                "• _descrizione Stipendio maggio_\n"
                "• _data ieri_",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text(
                "✏️ Cosa vuoi modificare?\n\n"
                "Scrivi ad esempio:\n"
                "• _importo 25_\n"
                "• _categoria Trasporti_\n"
                "• _descrizione Spesa Lidl_\n"
                "• _data ieri_",
                parse_mode="Markdown",
            )
        return WAITING_EDIT

    if query.data == "confirm" and expense:
        try:
            is_income = expense.type == "entrata"
            if is_income:
                append_income(expense)
            else:
                append_expense(expense)
                cfg_set("last_expense_date", expense.date)

            budget_msg = ""
            if idx + 1 >= total:
                parsed = datetime.strptime(expense.date, "%Y-%m-%d")
                if is_income:
                    budget_msg = f"\n\n📌 Budget di {parsed.strftime('%B')} aggiornato automaticamente a *€{expense.amount:.2f}*"
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

            if is_income:
                label = "Entrata"
                emoji = "💰"
            else:
                label = "Spesa"
                emoji = "✅"

            if total > 1:
                await query.edit_message_text(
                    f"{emoji} {label} {idx + 1}/{total} salvata: €{expense.amount:.2f} — {expense.description}" + budget_msg,
                    parse_mode="Markdown",
                )
            else:
                detail = f"€{expense.amount:.2f} — {expense.description if is_income else expense.category}\n_{expense.description}_" if not is_income else f"€{expense.amount:.2f} — {expense.description}"
                await query.edit_message_text(
                    f"{emoji} *{label} salvata!*\n\n{detail}" + budget_msg,
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
            "❓ Non ho capito la modifica. Riprova (es. 'importo 25' o 'categoria Trasporti')."
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
        await update.message.reply_text("⏱️ Tempo scaduto. Invia di nuovo la voce.")
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
