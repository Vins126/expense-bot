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
from config import AUTHORIZED_USER_ID
from services.transcribe import transcribe_audio, download_telegram_file
from services.extract import extract_expense, Expense
from services.sheets import append_expense

logger = logging.getLogger(__name__)

WAITING_CONFIRMATION = 1
_PENDING_EXPENSE_KEY = "pending_expense"


def _is_authorized(update: Update) -> bool:
    return update.effective_user.id == AUTHORIZED_USER_ID


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
            InlineKeyboardButton("❌ No", callback_data="cancel"),
        ]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_authorized(update):
        return
    await update.message.reply_text(
        "👋 Ciao! Inviami un messaggio vocale o scrivi la spesa.\n\n"
        "Esempio: *ho speso 12 euro al bar* oppure manda una nota vocale."
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

    expense: Expense | None = context.user_data.pop(_PENDING_EXPENSE_KEY, None)

    if query.data == "confirm" and expense:
        try:
            append_expense(expense)
            await query.edit_message_text(
                f"✅ *Spesa salvata!*\n\n"
                f"€{expense.amount:.2f} — {expense.category}\n_{expense.description}_",
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error("Errore salvataggio: %s", e)
            await query.edit_message_text("⚠️ Errore nel salvataggio. Riprova.")
    else:
        await query.edit_message_text("❌ Operazione annullata.")

    return ConversationHandler.END


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
                CallbackQueryHandler(handle_confirmation, pattern="^(confirm|cancel)$"),
            ],
        },
        fallbacks=[
            CommandHandler("start", start),
        ],
        conversation_timeout=120,
        per_message=False,
    )
