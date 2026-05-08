import logging
from telegram.ext import ApplicationBuilder, CommandHandler
from config import BOT_TOKEN
from bot.handlers import build_conversation_handler, start
from services.sheets import ensure_dashboard_sheet

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Avvio bot spese...")
    ensure_dashboard_sheet()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(build_conversation_handler())

    logger.info("Bot in ascolto (long polling)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
