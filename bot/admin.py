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

💬 *Registrare voci:*
• Messaggio vocale → trascrive e registra
• Testo libero → _"ho speso 10 euro al bar"_
• Entrata → _"ho ricevuto 1500 euro di stipendio"_
• Premi ✏️ Modifica per correggere prima di confermare

💰 *Statistiche e budget:*
/riepilogo — spese, entrate e saldo del mese corrente
/budget `<importo>` — imposta budget mensile (usato se non ci sono entrate)

🔄 *Costi fissi ricorrenti:*
/ricorrente — lista costi fissi
/ricorrente `<importo> <descrizione> [mesi]` — aggiunge costo fisso
/ricorrente del `<id>` — rimuove costo fisso

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
• Per entrate: _"ho ricevuto 1500 euro di stipendio"_

Il bot ti chiederà conferma prima di salvare.
Puoi premere ✏️ *Modifica* per correggere importo o categoria.
""".strip()


_INFO_TEXT = """
📖 *Guida al bot spese*

*Come registrare una spesa:*
Scrivi liberamente oppure invia una nota vocale:
• _"ho speso 25 euro al supermercato"_
• _"12€ caffè al bar"_
• _"ieri 50 euro all'Oasi"_
Puoi anche mandare la *foto di uno scontrino* — il bot legge automaticamente i prezzi.

*Come registrare un'entrata:*
• _"ho ricevuto 1500 euro di stipendio"_
Le entrate diventano il budget del mese automaticamente.

*Conferma della spesa:*
Il bot mostra sempre un riepilogo prima di salvare. Hai tre opzioni:
✅ *Sì* — salva
✏️ *Modifica* — correggi importo, categoria, descrizione o data \\(es. "importo 30" o "categoria Trasporti"\\)
❌ *No* — annulla

*Categorie disponibili:*
Ristoranti/Bar · Trasporti · Abbigliamento · Salute/Farmacia · Psicologa · Costi Fissi · Action · Oasi · EuroSpin · Acqua e Sapone · Altro
Il bot riconosce automaticamente il negozio o il tipo di spesa.

*Costi fissi ricorrenti \\(/ricorrente\\):*
Spese che si ripetono ogni mese o ogni N mesi \\(es. Spotify ogni 4 mesi\\).
Vengono registrati automaticamente il 1° del mese e ricevi una notifica.
• `/ricorrente` — vedi la lista
• `/ricorrente 9.99 Spotify 4` — aggiunge €9.99 ogni 4 mesi
• `/ricorrente 30 WiFi TIM` — aggiunge €30 ogni mese
• `/ricorrente del <id>` — rimuovi un costo fisso

*/riepilogo* — spese del mese corrente per categoria + saldo \\(entrate − spese\\)
*/budget <importo>* — imposta un budget mensile fisso \\(usato solo se non hai registrato entrate\\)
*/info* — questa guida
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
    budget_line = f"\n💰 Budget mensile (fallback): €{budget:.0f}" if budget else "\n💰 Budget manuale: non impostato"
    await update.message.reply_text(
        f"🤖 *Status Bot*\n\n"
        f"🟢 Online da: {hours}h {minutes}m\n"
        f"👥 Utenti autorizzati: {len(users)}"
        + budget_line +
        f"\n📦 Versione: v1.4.0",
        parse_mode="Markdown",
    )


async def cmd_budget(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    if not context.args:
        budget = cfg_get("budget")
        if budget:
            await update.message.reply_text(
                f"💰 Budget manuale: *€{budget:.0f}*\n\n"
                f"_Nota: se hai registrato entrate questo mese, vengono usate come budget al posto di questo valore._\n\n"
                f"Per modificarlo: /budget <importo>",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "💰 Nessun budget manuale impostato.\n\n"
                "Il budget viene calcolato automaticamente dalle entrate del mese.\n"
                "Per impostare un budget fisso di fallback: /budget <importo>"
            )
        return
    try:
        amount = float(context.args[0].replace(",", "."))
    except ValueError:
        await update.message.reply_text("Importo non valido.")
        return
    cfg_set("budget", amount)
    await update.message.reply_text(f"✅ Budget mensile (fallback) impostato a *€{amount:.0f}*", parse_mode="Markdown")


async def cmd_riepilogo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return
    await update.message.reply_text("⏳ Recupero dati...")
    from services.sheets import get_monthly_summary, get_monthly_income
    today = date.today()
    summary = get_monthly_summary(today.year, today.month)
    total_expenses = summary.pop("_total", 0.0)
    income = get_monthly_income(today.year, today.month)

    month_names = [
        "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
        "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
    ]

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
        pct_rimasto = ((income - total_expenses) / income * 100) if income > 0 else 0
        saldo_emoji = "✅" if saldo >= 0 else "🚨"
        lines.append(f"\n{saldo_emoji} *Saldo: €{saldo:.2f}* ({pct_rimasto:.0f}% disponibile)")
    elif total_expenses > 0:
        budget = cfg_get("budget")
        if budget:
            pct = (total_expenses / budget) * 100
            lines.append(f"\n📌 Budget: €{budget:.0f} — usato {pct:.0f}%")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_ricorrente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not _is_admin(update):
        return

    from services.recurring import load, add, remove

    args = context.args or []

    # /ricorrente del <id>
    if len(args) >= 2 and args[0].lower() == "del":
        item_id = args[1]
        if remove(item_id):
            await update.message.reply_text(f"✅ Costo fisso `{item_id}` rimosso.", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"⚠️ ID `{item_id}` non trovato.", parse_mode="Markdown")
        return

    # /ricorrente <importo> <descrizione...> [mesi]
    if len(args) >= 2:
        try:
            amount = float(args[0].replace(",", "."))
        except ValueError:
            await update.message.reply_text("Importo non valido. Esempio: /ricorrente 9.99 Spotify 4")
            return

        # Last arg is interval if it's a number, else default to 1
        interval = 1
        desc_args = args[1:]
        if desc_args and desc_args[-1].isdigit():
            interval = int(desc_args[-1])
            desc_args = desc_args[:-1]

        description = " ".join(desc_args).strip()
        if not description:
            await update.message.reply_text("Descrizione mancante. Esempio: /ricorrente 9.99 Spotify 4")
            return

        item = add(amount, description, interval)
        interval_str = f"ogni {interval} mesi" if interval > 1 else "mensile"
        await update.message.reply_text(
            f"✅ Costo fisso aggiunto:\n"
            f"• €{amount:.2f} — {description} ({interval_str})\n"
            f"• ID: `{item.id}`\n"
            f"• Prima scadenza: {item.next_due}",
            parse_mode="Markdown",
        )
        return

    # /ricorrente → lista
    items = load()
    if not items:
        await update.message.reply_text(
            "Nessun costo fisso configurato.\n\n"
            "Aggiungi con: /ricorrente <importo> <descrizione> [mesi]\n"
            "Esempio: /ricorrente 9.99 Spotify 4"
        )
        return

    lines = ["🔄 *Costi fissi ricorrenti:*\n"]
    for item in items:
        interval_str = f"ogni {item.interval_months} mesi" if item.interval_months > 1 else "mensile"
        lines.append(f"• `{item.id}` — €{item.amount:.2f} {item.description} ({interval_str})\n  Prossima: {item.next_due}")
    lines.append("\nPer rimuovere: /ricorrente del <id>")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id not in get_users():
        return
    await update.message.reply_text(_INFO_TEXT, parse_mode="MarkdownV2")


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
