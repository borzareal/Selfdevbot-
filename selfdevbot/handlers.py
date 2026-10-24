"""Commandes Telegram, questionnaire d'accueil et conversation libre."""

import logging
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from telegram import ReplyKeyboardMarkup, ReplyKeyboardRemove, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from .ai import format_profile
from .scheduler import schedule_reminder, schedule_user, send_proactive, unschedule_user
from .utils import clean_days, format_days, parse_hhmm, parse_local_datetime, resolve_timezone, split_message, validate_checkins

log = logging.getLogger(__name__)

ASKING = 0

# (clé du profil, question, boutons de réponse rapide éventuels)
QUESTIONS = [
    ("name", "Pour commencer, comment veux-tu que je t'appelle ?", None),
    ("goals", "Qu'est-ce que tu veux accomplir ? Donne-moi tes objectifs, à court et à long terme "
              "(sport, études, business, mental, relations...).", None),
    ("bad_habits", "Sois honnête avec moi : quelles sont tes mauvaises habitudes ? Et à quel moment "
                   "elles te tombent dessus en général ? (ex : scroller TikTok au lit à minuit)", None),
    ("schedule", "Décris-moi ton emploi du temps type, en semaine et le week-end "
                 "(cours/taf, salle, trajets, temps libre...).", None),
    ("wake_time", "À quelle heure tu te lèves (ou veux te lever) ?", None),
    ("bed_time", "À quelle heure tu dois te coucher ?", None),
    ("meals", "À quelles heures tu manges d'habitude (ou voudrais manger) ?", None),
    ("city", "Tu vis dans quelle ville ? (pour caler l'heure de mes messages)", None),
    ("tone", "Tu veux quel style de coach ?",
     [["Doux et encourageant"], ["Équilibré"], ["Strict, qui ne lâche rien"]]),
    ("frequency", "Combien de messages par jour de ma part ?",
     [["3-4 (léger)"], ["5-7 (normal)"], ["8-10 (intensif)"]]),
]


def max_messages_per_day(answer: str) -> int:
    numbers = [int(n) for n in re.findall(r"\d+", answer or "")]
    return min(max(numbers), 12) if numbers else 6


def build_system_prompt(context: ContextTypes.DEFAULT_TYPE, user: dict) -> str:
    db = context.bot_data["db"]
    chat_id = user["chat_id"]
    return context.bot_data["coach"].persona(
        user,
        datetime.now(ZoneInfo(user["timezone"])),
        db.list_memories(chat_id),
        db.list_checkins(chat_id),
        db.pending_reminders(chat_id),
    )


async def reply(update: Update, text: str, **kwargs) -> None:
    for chunk in split_message(text):
        await update.effective_message.reply_text(chunk, **kwargs)


# --- Questionnaire d'accueil -------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    db = context.bot_data["db"]
    cfg = context.bot_data["config"]
    chat = update.effective_chat
    db.ensure_user(chat.id, update.effective_user.first_name, cfg.default_timezone)

    user = db.get_user(chat.id)
    if user["onboarded"] and update.message.text.startswith("/start"):
        await reply(update, "On se connaît déjà 😉 Écris-moi quand tu veux. "
                            "Tape /refaire si tu veux refaire le questionnaire, /aide pour les commandes.")
        return ConversationHandler.END

    context.user_data["answers"] = {}
    context.user_data["step"] = 0
    await reply(
        update,
        f"Enchanté. Je suis {cfg.bot_name}, ton assistant personnel.\n\n"
        "Mon job : t'aider à devenir la meilleure version de toi-même. Je t'écrirai de moi-même au bon "
        "moment pour te rappeler tes objectifs, te pousser quand il faut, et faire le point avec toi.\n\n"
        f"Avant ça, j'ai {len(QUESTIONS)} questions pour te connaître. Réponds librement, "
        "il n'y a pas de mauvaise réponse. (/annuler pour arrêter)",
    )
    await ask(update, 0)
    return ASKING


async def ask(update: Update, step: int) -> None:
    _, question, buttons = QUESTIONS[step]
    markup = (ReplyKeyboardMarkup(buttons, one_time_keyboard=True, resize_keyboard=True)
              if buttons else ReplyKeyboardRemove())
    await reply(update, f"({step + 1}/{len(QUESTIONS)}) {question}", reply_markup=markup)


async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    step = context.user_data.get("step", 0)
    key = QUESTIONS[step][0]
    # Réponses libres acceptées telles quelles ("vers 23h, 1h le week-end") : le modèle interprète.
    context.user_data["answers"][key] = update.message.text.strip()

    step += 1
    context.user_data["step"] = step
    if step < len(QUESTIONS):
        await ask(update, step)
        return ASKING

    await finish_onboarding(update, context)
    return ConversationHandler.END


async def finish_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = context.bot_data["db"]
    coach = context.bot_data["coach"]
    cfg = context.bot_data["config"]
    chat_id = update.effective_chat.id
    profile = context.user_data.pop("answers")

    await reply(update, "Parfait. Je prépare ton programme, une seconde…", reply_markup=ReplyKeyboardRemove())
    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)

    plan = await coach.build_plan(profile, max_messages_per_day(profile.get("frequency", "")))
    tz = resolve_timezone(plan.get("timezone"), cfg.default_timezone)
    checkins = validate_checkins(plan.get("checkins"))
    if not checkins:
        wake = parse_hhmm(profile.get("wake_time", "")) or parse_hhmm("08:00")
        checkins = [
            {"time": wake.strftime("%H:%M"), "days": list(range(7)),
             "purpose": "Message du matin : motivation et ses 3 priorités du jour."},
            {"time": "21:30", "days": list(range(7)),
             "purpose": "Bilan du soir : ce qui a marché, ce qui n'a pas marché, objectif de demain."},
        ]

    db.save_onboarding(chat_id, profile, tz, plan.get("summary", ""))
    db.replace_checkins(chat_id, checkins)
    schedule_user(context.job_queue, db, chat_id)

    name = profile.get("name") or "toi"
    await reply(
        update,
        f"C'est noté, {name}. Voici quand je vais t'écrire ({tz}) :\n\n"
        + planning_text(db, chat_id)
        + "\n\nTu peux aussi m'écrire n'importe quand : me raconter ta journée, me demander un conseil, "
          "ou me dire « rappelle-moi demain à 18h d'appeler ma mère ». "
          "Si un horaire ne te va pas, dis-le-moi simplement et je l'ajuste.",
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await reply(update, "Questionnaire annulé. Tape /start quand tu veux reprendre.",
                reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


# --- Commandes ---------------------------------------------------------------

def planning_text(db, chat_id: int) -> str:
    lines = [f"• {c['time']} ({format_days(c['days'])}) — {c['purpose']}" for c in db.list_checkins(chat_id)]
    user = db.get_user(chat_id)
    tz = ZoneInfo(user["timezone"])
    reminders = db.pending_reminders(chat_id)
    if reminders:
        lines.append("\nRappels ponctuels :")
        for r in reminders:
            local = datetime.fromisoformat(r["run_at"]).astimezone(tz)
            lines.append(f"• {local:%d/%m à %H:%M} — {r['text']}")
    return "\n".join(lines) or "Rien de prévu pour l'instant."


async def require_onboarded(update: Update, context: ContextTypes.DEFAULT_TYPE) -> dict | None:
    user = context.bot_data["db"].get_user(update.effective_chat.id)
    if not user or not user["onboarded"]:
        await reply(update, "On ne se connaît pas encore. Tape /start pour commencer.")
        return None
    return user


async def planning(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_onboarded(update, context):
        await reply(update, planning_text(context.bot_data["db"], update.effective_chat.id))


async def profil(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await require_onboarded(update, context)
    if user:
        await reply(update, "Ce que je sais de toi :\n" + format_profile(user["profile"]))


async def pause(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_onboarded(update, context):
        context.bot_data["db"].set_paused(update.effective_chat.id, True)
        await reply(update, "Compris, je me fais discret. Je ne t'écris plus de moi-même jusqu'à /reprendre.")


async def reprendre(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_onboarded(update, context):
        context.bot_data["db"].set_paused(update.effective_chat.id, False)
        await reply(update, "Je reprends du service. 🫡")


async def coach_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if await require_onboarded(update, context):
        await context.bot.send_chat_action(update.effective_chat.id, ChatAction.TYPING)
        await send_proactive(context, update.effective_chat.id,
                             "Il te demande de passer le voir : prends de ses nouvelles et pousse-le "
                             "sur sa priorité la plus importante à cette heure-ci.")


async def oublie(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args != ["confirmer"]:
        await reply(update, "Ça efface tout ton profil et notre historique. "
                            "Si tu es sûr, tape : /oublie confirmer")
        return
    chat_id = update.effective_chat.id
    unschedule_user(context.job_queue, chat_id)
    context.bot_data["db"].delete_user(chat_id)
    await reply(update, "Tout est effacé. Tape /start si tu veux recommencer un jour.")


async def aide(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await reply(
        update,
        "Écris-moi normalement, je comprends le langage naturel (« décale mon rappel salle à 18h », "
        "« rappelle-moi vendredi à 10h de payer le loyer »...).\n\n"
        "/planning — quand je vais t'écrire\n"
        "/profil — ce que je sais de toi\n"
        "/coach — je t'écris un message maintenant\n"
        "/pause — je ne t'écris plus de moi-même\n"
        "/reprendre — je recommence\n"
        "/refaire — refaire le questionnaire\n"
        "/oublie — tout effacer",
    )


# --- Conversation libre ------------------------------------------------------

def make_tool_executor(context: ContextTypes.DEFAULT_TYPE, user: dict):
    db = context.bot_data["db"]
    chat_id = user["chat_id"]

    async def execute(name: str, args: dict) -> dict:
        if name == "create_reminder":
            when = parse_local_datetime(args.get("when", ""), user["timezone"])
            if not when:
                return {"ok": False, "error": "Format de date invalide, utilise YYYY-MM-DDTHH:MM"}
            if when <= datetime.now(timezone.utc):
                return {"ok": False, "error": "Cette date est déjà passée"}
            rid = db.add_reminder(chat_id, when, args["text"])
            schedule_reminder(context.job_queue, db.get_reminder(rid))
            return {"ok": True, "id": rid}

        if name == "add_recurring_checkin":
            t = parse_hhmm(args.get("time", ""))
            if not t:
                return {"ok": False, "error": "Heure invalide, utilise HH:MM"}
            cid = db.add_checkin(chat_id, t.strftime("%H:%M"), clean_days(args.get("days")), args["purpose"])
            schedule_user(context.job_queue, db, chat_id)
            return {"ok": True, "id": cid}

        if name == "remove_checkin":
            ok = db.remove_checkin(chat_id, int(args["id"]))
            schedule_user(context.job_queue, db, chat_id)
            return {"ok": ok}

        if name == "cancel_reminder":
            rid = int(args["id"])
            ok = db.delete_reminder(chat_id, rid)
            for job in context.job_queue.get_jobs_by_name(f"reminder:{chat_id}:{rid}"):
                job.schedule_removal()
            return {"ok": ok}

        if name == "update_profile":
            db.update_profile_field(chat_id, args["field"], args["value"])
            return {"ok": True}

        if name == "remember":
            db.add_memory(chat_id, args["fact"])
            return {"ok": True}

        return {"ok": False, "error": f"Outil inconnu : {name}"}

    return execute


async def chat(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = await require_onboarded(update, context)
    if not user:
        return
    db = context.bot_data["db"]
    chat_id = user["chat_id"]
    text = update.message.text

    await context.bot.send_chat_action(chat_id, ChatAction.TYPING)
    history = db.recent_messages(chat_id)
    answer_text = await context.bot_data["coach"].chat(
        build_system_prompt(context, user), history, text, make_tool_executor(context, user)
    )
    db.add_message(chat_id, "user", text)
    if answer_text:
        db.add_message(chat_id, "assistant", answer_text)
        await reply(update, answer_text)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Erreur pendant le traitement d'un message", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text("Petit souci technique de mon côté, réessaie dans un instant.")


def register(app: Application, allowed_user_ids: frozenset[int]) -> None:
    allowed = filters.User(user_id=list(allowed_user_ids)) if allowed_user_ids else filters.ALL

    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler(["start", "refaire"], start, filters=allowed)],
        states={ASKING: [MessageHandler(allowed & filters.TEXT & ~filters.COMMAND, answer)]},
        fallbacks=[CommandHandler("annuler", cancel, filters=allowed)],
    ))
    for name, fn in [("planning", planning), ("profil", profil), ("pause", pause),
                     ("reprendre", reprendre), ("coach", coach_now), ("oublie", oublie), ("aide", aide)]:
        app.add_handler(CommandHandler(name, fn, filters=allowed))
    app.add_handler(MessageHandler(allowed & filters.TEXT & ~filters.COMMAND, chat))
    app.add_error_handler(on_error)
