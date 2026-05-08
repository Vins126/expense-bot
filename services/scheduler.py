import logging
from datetime import datetime, date, timedelta, time, timezone
from telegram.ext import ContextTypes
from services.sheets import get_monthly_summary, get_weekly_summary
from services.storage import get_users
from services.config_store import get, set as cfg_set

logger = logging.getLogger(__name__)

_UTC = timezone.utc


def _format_summary(summary: dict, title: str) -> str:
    total = summary.pop("_total", 0.0)
    if total == 0:
        return f"{title}\n\nNessuna spesa registrata."
    lines = [f"{title}\n"]
    for cat, amount in sorted(summary.items(), key=lambda x: -x[1]):
        lines.append(f"• {cat}: €{amount:.2f}")
    lines.append(f"\n💰 *Totale: €{total:.2f}*")
    return "\n".join(lines)


async def weekly_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Invio riepilogo settimanale")
    summary = get_weekly_summary()
    text = _format_summary(summary, "📊 *Riepilogo settimanale*")
    for user_id in get_users():
        try:
            await context.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.warning("Impossibile inviare a %s: %s", user_id, e)


async def monthly_summary(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Invio riepilogo mensile")
    prev = date.today().replace(day=1) - timedelta(days=1)
    summary = get_monthly_summary(prev.year, prev.month)
    month_names = [
        "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
        "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
    ]

    budget = get("budget")
    total = summary.get("_total", 0.0)
    budget_line = ""
    if budget:
        pct = (total / budget) * 100
        budget_line = f"\n📌 Budget mensile: €{budget:.0f} — usato {pct:.0f}%"

    text = _format_summary(summary, f"📅 *Riepilogo {month_names[prev.month]} {prev.year}*") + budget_line
    for user_id in get_users():
        try:
            await context.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
        except Exception as e:
            logger.warning("Impossibile inviare a %s: %s", user_id, e)


async def inactivity_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    last_str = get("last_expense_date")
    if not last_str:
        return
    last = date.fromisoformat(last_str)
    days_ago = (date.today() - last).days
    if days_ago >= 3:
        logger.info("Reminder inattività: %d giorni senza spese", days_ago)
        text = f"💭 Sono passati {days_ago} giorni dall'ultima spesa registrata. Hai dimenticato qualcosa?"
        for user_id in get_users():
            try:
                await context.bot.send_message(chat_id=user_id, text=text)
            except Exception as e:
                logger.warning("Impossibile inviare a %s: %s", user_id, e)


def register_jobs(app) -> None:
    jq = app.job_queue
    # Weekly summary: every Sunday at 19:00 UTC (≈ 21:00 Italian summer)
    jq.run_daily(weekly_summary, time=time(19, 0, tzinfo=_UTC), days=(6,))
    # Monthly summary: 1st of each month at 18:00 UTC
    jq.run_monthly(monthly_summary, when=time(18, 0, tzinfo=_UTC), day=1)
    # Inactivity check: every day at 10:00 UTC
    jq.run_daily(inactivity_check, time=time(10, 0, tzinfo=_UTC))
    logger.info("Job schedulati: riepilogo settimanale, mensile, inattività")
