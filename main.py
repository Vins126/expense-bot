import logging
import os
import sys
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

_PID_FILE = "/tmp/expense-bot.pid"


def _acquire_pid_lock() -> None:
    if os.path.exists(_PID_FILE):
        with open(_PID_FILE) as f:
            old_pid = f.read().strip()
        # Check if that process is actually still running
        try:
            os.kill(int(old_pid), 0)
            alive = True
        except (OSError, ValueError):
            alive = False
        if alive:
            logger.error("Bot già in esecuzione (PID %s). Uscita.", old_pid)
            sys.exit(1)
    with open(_PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _release_pid_lock() -> None:
    if os.path.exists(_PID_FILE):
        os.remove(_PID_FILE)


def main() -> None:
    _acquire_pid_lock()
    try:
        logger.info("Avvio bot spese...")
        ensure_dashboard_sheet()

        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(build_conversation_handler())

        logger.info("Bot in ascolto (long polling)...")
        app.run_polling(drop_pending_updates=True)
    finally:
        _release_pid_lock()


if __name__ == "__main__":
    main()
