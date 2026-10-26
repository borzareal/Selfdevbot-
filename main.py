import logging

from telegram import BotCommand
from telegram.ext import Application

from selfdevbot.ai import Coach, explain_ai_error
from selfdevbot.config import load_config
from selfdevbot.db import Database
from selfdevbot.handlers import register
from selfdevbot.scheduler import schedule_all
from selfdevbot.voice import Voice

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("selfdevbot")

COMMANDS = [
    ("planning", "Quand je vais t'écrire"),
    ("profil", "Ce que je sais de toi"),
    ("coach", "Je t'écris maintenant"),
    ("pause", "Je ne t'écris plus de moi-même"),
    ("reprendre", "Je recommence à t'écrire"),
    ("refaire", "Refaire le questionnaire"),
    ("aide", "Aide"),
]


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([BotCommand(c, d) for c, d in COMMANDS])
    schedule_all(app)
    coach = app.bot_data["coach"]
    try:
        await coach.check()
        log.info("IA OK (modèle %s). Le bot est prêt, envoie /start sur Telegram.", coach.model)
    except Exception as e:
        log.error("PROBLÈME AVEC L'IA : %s", explain_ai_error(e))


def main() -> None:
    cfg = load_config()
    app = Application.builder().token(cfg.telegram_token).post_init(post_init).build()
    app.bot_data["config"] = cfg
    app.bot_data["db"] = Database(cfg.database_path)
    app.bot_data["coach"] = Coach(cfg.ai_api_key, cfg.ai_model, cfg.bot_name,
                                  base_url=cfg.ai_base_url, json_mode=cfg.json_mode,
                                  fallback_models=cfg.ai_fallback_models)
    if cfg.elevenlabs_api_key:
        app.bot_data["voice"] = Voice(cfg.elevenlabs_api_key, cfg.elevenlabs_voice_id, cfg.elevenlabs_model)
        log.info("Vocaux ElevenLabs activés (finis un message par ans=voc).")
    register(app, cfg.allowed_user_ids)
    app.run_polling()


if __name__ == "__main__":
    main()
