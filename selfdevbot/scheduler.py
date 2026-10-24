"""Planification des messages envoyés par le bot de lui-même (JobQueue de python-telegram-bot)."""

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from telegram.ext import Application, ContextTypes, JobQueue

from .utils import parse_hhmm, split_message, to_ptb_days

log = logging.getLogger(__name__)


def _checkin_job_name(chat_id: int, checkin_id: int) -> str:
    return f"checkin:{chat_id}:{checkin_id}"


def unschedule_user(job_queue: JobQueue, chat_id: int) -> None:
    prefix = f"checkin:{chat_id}:"
    for job in job_queue.jobs():
        if job.name and (job.name.startswith(prefix) or job.name.startswith(f"reminder:{chat_id}:")):
            job.schedule_removal()


def schedule_user(job_queue: JobQueue, db, chat_id: int) -> None:
    """(Re)programme tous les check-ins récurrents d'un utilisateur."""
    prefix = f"checkin:{chat_id}:"
    for job in job_queue.jobs():
        if job.name and job.name.startswith(prefix):
            job.schedule_removal()

    user = db.get_user(chat_id)
    if not user or not user["onboarded"]:
        return
    tz = ZoneInfo(user["timezone"])
    for c in db.list_checkins(chat_id):
        t = parse_hhmm(c["time"])
        if not t:
            continue
        job_queue.run_daily(
            checkin_job,
            time=t.replace(tzinfo=tz),
            days=to_ptb_days(c["days"]),
            name=_checkin_job_name(chat_id, c["id"]),
            chat_id=chat_id,
            data={"checkin_id": c["id"]},
        )


def schedule_reminder(job_queue: JobQueue, reminder: dict) -> None:
    run_at = datetime.fromisoformat(reminder["run_at"])
    job_queue.run_once(
        reminder_job,
        when=max(run_at, datetime.now(timezone.utc)),
        name=f"reminder:{reminder['chat_id']}:{reminder['id']}",
        chat_id=reminder["chat_id"],
        data={"reminder_id": reminder["id"]},
    )


def schedule_all(app: Application) -> None:
    db = app.bot_data["db"]
    for user in db.onboarded_users():
        schedule_user(app.job_queue, db, user["chat_id"])
    for r in db.pending_reminders():
        schedule_reminder(app.job_queue, r)  # rappels ratés pendant un redémarrage : envoyés tout de suite
    log.info("%d tâches planifiées", len(app.job_queue.jobs()))


async def send_proactive(context: ContextTypes.DEFAULT_TYPE, chat_id: int, purpose: str) -> None:
    from .handlers import build_system_prompt  # import local : évite un cycle

    db = context.bot_data["db"]
    coach = context.bot_data["coach"]
    user = db.get_user(chat_id)
    if not user or not user["onboarded"] or user["paused"]:
        return
    system = build_system_prompt(context, user)
    text = await coach.proactive_message(system, db.recent_messages(chat_id), purpose)
    if not text:
        return
    for chunk in split_message(text):
        await context.bot.send_message(chat_id=chat_id, text=chunk)
    db.add_message(chat_id, "assistant", text)


async def checkin_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    job = context.job
    checkin = next(
        (c for c in context.bot_data["db"].list_checkins(job.chat_id) if c["id"] == job.data["checkin_id"]),
        None,
    )
    if not checkin:
        job.schedule_removal()
        return
    try:
        await send_proactive(context, job.chat_id, checkin["purpose"])
    except Exception:
        log.exception("Check-in %s en échec", job.name)


async def reminder_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    reminder = db.get_reminder(context.job.data["reminder_id"])
    if not reminder or reminder["sent"]:
        return
    try:
        await send_proactive(context, reminder["chat_id"], f"Rappel qu'il t'a demandé : {reminder['text']}")
    except Exception:
        log.exception("Rappel %s en échec", reminder["id"])
    db.mark_reminder_sent(reminder["id"])
