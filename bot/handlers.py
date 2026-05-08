import logging
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
from services.extract import extract_expense, apply_edit, Expense
from services.sheets import append_expense
from services.storage import get_users
from services.config_store import get as cfg_get, set as cfg_set

logger = logging.getLogger(__name__)

WAITING_CONFIRMATION = 1
WAITING_EDIT = 2
_PENDING_EXPENSE_KEY = "pending_expense"


def _is_authorized(update: Update) -> bool:
    return update.effective_user.id in get_users()


def _expense_preview(expense: Expense) -> str:
    return (
        f"📝 *Ho capito questa spesa:*\n\n"
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


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    await update.message.reply_text(
        "👋 Ciao! Inviami un messaggio vocale o scrivi la spesa.\n\n"
        "Esempio: *ho speso 12 euro al bar* oppure manda una nota vocale.\n"
        "Usa /help per vedere tutti i comandi."
        , parse_mode="Markdown"
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


async def _process_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str) -> int:
    expense = extract_expense(text)

    if expense is None:
        await update.message.reply_text(
            "❓ Non sono riuscito a capire la spesa. Riprova con un messaggio più chiaro.\n"
            "Esempio: *ho speso 25 euro al supermercato*",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    context.user_data[_PENDING_EXPENSE_KEY] = expense
    await update.message.reply_text(
        _expense_preview(expense),
        parse_mode="Markdown",
        reply_markup=_confirm_keyboard(),
    )
    return WAITING_CONFIRMATION


async def handle_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "edit":
        await query.edit_message_text(
            "✏️ Cosa vuoi modificare?\n\n"
            "Scrivi ad esempio:\n"
            "• _importo 25_\n"
            "• _categoria Trasporti_\n"
            "• _data ieri_",
            parse_mode="Markdown",
        )
        return WAITING_EDIT

    expense: Expense | None = context.user_data.pop(_PENDING_EXPENSE_KEY, None)

    if query.data == "confirm" and expense:
        try:
            append_expense(expense)
            cfg_set("last_expense_date", expense.date)

            # Budget check
            from datetime import datetime
            parsed = datetime.strptime(expense.date, "%Y-%m-%d")
            budget = cfg_get("budget")
            budget_msg = ""
            if budget:
                from services.sheets import get_monthly_summary
                summary = get_monthly_summary(parsed.year, parsed.month)
                total = summary.get("_total", 0.0)
                pct = (total / budget) * 100
                if pct >= 100:
                    budget_msg = f"\n\n🚨 *Budget superato!* Hai speso €{total:.2f} su €{budget:.0f} ({pct:.0f}%)"
                elif pct >= 80:
                    budget_msg = f"\n\n⚠️ Attenzione: hai usato l'*{pct:.0f}%* del budget (€{total:.2f} / €{budget:.0f})"

            await query.edit_message_text(
                f"✅ *Spesa salvata!*\n\n"
                f"€{expense.amount:.2f} — {expense.category}\n_{expense.description}_"
                + budget_msg,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error("Errore salvataggio: %s", e)
            await query.edit_message_text("⚠️ Errore nel salvataggio. Riprova.")
    else:
        await query.edit_message_text("❌ Operazione annullata.")

    return ConversationHandler.END


async def handle_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    expense: Expense | None = context.user_data.get(_PENDING_EXPENSE_KEY)
    if not expense:
        await update.message.reply_text("❌ Nessuna spesa in attesa. Inizia da capo.")
        return ConversationHandler.END

    edit_text = update.message.text.strip()
    updated = apply_edit(expense, edit_text)

    if updated is None:
        await update.message.reply_text(
            "❓ Non ho capito la modifica. Riprova (es. 'importo 25' o 'categoria Trasporti')."
        )
        return WAITING_EDIT

    context.user_data[_PENDING_EXPENSE_KEY] = updated
    await update.message.reply_text(
        _expense_preview(updated),
        parse_mode="Markdown",
        reply_markup=_confirm_keyboard(),
    )
    return WAITING_CONFIRMATION


async def handle_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop(_PENDING_EXPENSE_KEY, None)
    if update.message:
        await update.message.reply_text("⏱️ Tempo scaduto. Invia di nuovo la spesa.")
    return ConversationHandler.END


def build_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[
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
