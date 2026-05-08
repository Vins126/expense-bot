import logging
import logging.handlers
import os
import sys
from pathlib import Path
from telegram import BotCommand
from telegram.ext import Application, ApplicationBuilder, CommandHandler
from config import BOT_TOKEN, AUTHORIZED_USER_IDS
from bot.handlers import build_conversation_handler, start
from bot.admin import (
    cmd_adduser, cmd_removeuser, cmd_listusers, cmd_logs,
    cmd_status, cmd_help, cmd_budget, cmd_riepilogo, cmd_broadcast,
)
from services.sheets import ensure_dashboard_sheet, ensure_charts_sheet
from services.storage import initialize_users
from services.config_store import load_config
from services.scheduler import register_jobs
import services.health as health

_DATA_DIR = Path(__file__).parent / "data"
_DATA_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            _DATA_DIR / "bot.log",
            maxBytes=100_000,   # ~500 lines
            backupCount=1,
        ),
    ],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

_PID_FILE = "/tmp/expense-bot.pid"


def _acquire_pid_lock() -> None:
    if os.path.exists(_PID_FILE):
        with open(_PID_FILE) as f:
            old_pid = f.read().strip()
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
        logger.info("Avvio bot spese v1.3.0...")
        load_config()
        initialize_users(AUTHORIZED_USER_IDS)
        ensure_dashboard_sheet()
        ensure_charts_sheet()
        health.start(port=8080)
        logger.info("Health check attivo su :8080/health")

        async def post_init(application: Application) -> None:
            await application.bot.set_my_commands([
                BotCommand("help", "Lista comandi"),
                BotCommand("riepilogo", "Totale spese mese corrente"),
                BotCommand("budget", "Imposta budget mensile"),
                BotCommand("status", "Stato e uptime del bot"),
                BotCommand("listusers", "Utenti autorizzati"),
                BotCommand("adduser", "Aggiungi utente: /adduser <id>"),
                BotCommand("removeuser", "Rimuovi utente: /removeuser <id>"),
                BotCommand("broadcast", "Messaggio a tutti: /broadcast <testo>"),
                BotCommand("logs", "Ultimi log del bot"),
            ])

        app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

        app.add_handler(CommandHandler("start", start))
        app.add_handler(CommandHandler("help", cmd_help))
        app.add_handler(CommandHandler("riepilogo", cmd_riepilogo))
        app.add_handler(CommandHandler("budget", cmd_budget))
        app.add_handler(CommandHandler("adduser", cmd_adduser))
        app.add_handler(CommandHandler("removeuser", cmd_removeuser))
        app.add_handler(CommandHandler("listusers", cmd_listusers))
        app.add_handler(CommandHandler("broadcast", cmd_broadcast))
        app.add_handler(CommandHandler("logs", cmd_logs))
        app.add_handler(CommandHandler("status", cmd_status))
        app.add_handler(build_conversation_handler())

        register_jobs(app)

        logger.info("Bot in ascolto (long polling)...")
        app.run_polling(drop_pending_updates=True)
    finally:
        _release_pid_lock()


if __name__ == "__main__":
    main()
