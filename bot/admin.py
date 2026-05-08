import logging
from datetime import datetime, date
from pathlib import Path
from telegram import Update
from telegram.ext import ContextTypes
from config import ADMIN_USER_ID
from services.storage import get_users, add_user, remove_user
from services.runtime import START_TIME
from services.config_store import get as cfg_get, set as cfg_set

logger = logging.getLogger(__name__)

_LOG_FILE = Path(__file__).parent.parent / "data" / "bot.log"

_HELP_ADMIN = """
📋 *Comandi disponibili*

💬 *Spese:*
• Messaggio vocale → trascrive e registra
• Testo libero → _"ho speso 10 euro al bar"_
• Premi ✏️ Modifica per correggere prima di confermare

💰 *Statistiche:*
/riepilogo — totale mese corrente per categoria
/budget `<importo>` — imposta budget mensile

🔧 *Admin:*
/adduser `<id>` — aggiunge utente autorizzato
/removeuser `<id>` — rimuove utente autorizzato
/listusers — lista utenti autorizzati
/broadcast `<testo>` — invia messaggio a tutti
/logs — ultimi log del bot
/status — stato e uptime del bot
/help — questo messaggio
""".strip()

_HELP_USER = """
📋 *Come usare il bot:*

• Invia un *messaggio vocale* con la spesa
• Oppure scrivi: _"ho speso 15 euro al supermercato"_

Il bot ti chiederà conferma prima di salvare.
Puoi premere ✏️ *Modifica* per correggere importo o categoria.
""".strip()


def _is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_USER_ID


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if _is_admin(update):
        await update.message.reply_text(_HELP_ADMIN, parse_mode="Markdown")
    else:
        await update.message.reply_text(_HELP_USER, parse_mode="Markdown")


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
    uptime = datetime.now() - START_TIME
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes = remainder // 60
    users = get_users()
    budget = cfg_get("budget")
    budget_line = f"\n💰 Budget mensile: €{budget:.0f}" if budget else "\n💰 Budget: non impostato"
    await update.message.reply_text(
        f"🤖 *Status Bot*\n\n"
        f"🟢 Online da: {hours}h {minutes}m\n"
        f"👥 Utenti autorizzati: {len(users)}"
        + budget_line +
        f"\n📦 Versione: v1.3.0",
        parse_mode="Markdown",
    )


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    if not context.args:
        budget = cfg_get("budget")
        if budget:
            await update.message.reply_text(f"💰 Budget mensile attuale: *€{budget:.0f}*\n\nPer modificarlo: /budget <importo>", parse_mode="Markdown")
        else:
            await update.message.reply_text("💰 Nessun budget impostato.\n\nUso: /budget <importo>")
        return
    try:
        amount = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Importo non valido.")
        return
    cfg_set("budget", amount)
    await update.message.reply_text(f"✅ Budget mensile impostato a *€{amount:.0f}*", parse_mode="Markdown")


async def cmd_riepilogo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    await update.message.reply_text("⏳ Recupero dati...")
    from services.sheets import get_monthly_summary
    today = date.today()
    summary = get_monthly_summary(today.year, today.month)
    total = summary.pop("_total", 0.0)
    month_names = [
        "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
        "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
    ]
    if total == 0:
        await update.message.reply_text(f"📊 Nessuna spesa registrata a {month_names[today.month]}.")
        return

    lines = [f"📊 *Riepilogo {month_names[today.month]} {today.year}*\n"]
    for cat, amount in sorted(summary.items(), key=lambda x: -x[1]):
        lines.append(f"• {cat}: €{amount:.2f}")
    lines.append(f"\n💰 *Totale: €{total:.2f}*")

    budget = cfg_get("budget")
    if budget:
        pct = (total / budget) * 100
        lines.append(f"📌 Budget: €{budget:.0f} — usato {pct:.0f}%")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    if not context.args:
        await update.message.reply_text("Uso: /broadcast <messaggio>")
        return
    text = " ".join(context.args)
    users = get_users()
    sent, failed = 0, 0
    for user_id in users:
        if user_id == update.effective_user.id:
            continue
        try:
            await context.bot.send_message(chat_id=user_id, text=f"📢 {text}")
            sent += 1
        except Exception as e:
            logger.warning("Broadcast fallito per %s: %s", user_id, e)
            failed += 1
    await update.message.reply_text(f"✅ Inviato a {sent} utenti" + (f", {failed} falliti" if failed else ""))
