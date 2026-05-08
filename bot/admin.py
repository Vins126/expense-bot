import logging
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_USER_ID
from services.storage import get_users, add_user, remove_user
from services.runtime import START_TIME

logger = logging.getLogger(__name__)

_LOG_FILE = Path(__file__).parent.parent / "data" / "bot.log"


def _is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_USER_ID


async def cmd_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /adduser <user_id>")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID non valido. Deve essere un numero.")
        return
    add_user(user_id)
    await update.message.reply_text(f"✅ Utente `{user_id}` aggiunto.", parse_mode="Markdown")


async def cmd_removeuser(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /removeuser <user_id>")
        return
    try:
        user_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("ID non valido. Deve essere un numero.")
        return
    if user_id == ADMIN_USER_ID:
        await update.message.reply_text("⛔ Non puoi rimuovere te stesso.")
        return
    if remove_user(user_id):
        await update.message.reply_text(f"✅ Utente `{user_id}` rimosso.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"⚠️ Utente `{user_id}` non trovato.", parse_mode="Markdown")


async def cmd_listusers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    users = sorted(get_users())
    if not users:
        await update.message.reply_text("Nessun utente autorizzato.")
        return
    lines = [f"• `{uid}`{'  ← admin' if uid == ADMIN_USER_ID else ''}" for uid in users]
    await update.message.reply_text(
        "👥 *Utenti autorizzati:*\n" + "\n".join(lines),
        parse_mode="Markdown",
    )


async def cmd_logs(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    if not _LOG_FILE.exists():
        await update.message.reply_text("Nessun log disponibile.")
        return
    lines = _LOG_FILE.read_text(errors="replace").splitlines()
    last = lines[-25:] if len(lines) > 25 else lines
    text = "\n".join(last)
    if len(text) > 3900:
        text = "..." + text[-3900:]
    await update.message.reply_text(f"```\n{text}\n```", parse_mode="Markdown")


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    import datetime
    uptime = datetime.datetime.now() - START_TIME
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes = remainder // 60
    users = get_users()
    await update.message.reply_text(
        f"🤖 *Status Bot*\n\n"
        f"🟢 Online da: {hours}h {minutes}m\n"
        f"👥 Utenti autorizzati: {len(users)}\n"
        f"📦 Versione: v1.2.0",
        parse_mode="Markdown",
    )
