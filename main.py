import logging

from telegram import BotCommand
from telegram.ext import Application

from selfdevbot.ai import Coach
from selfdevbot.config import load_config
from selfdevbot.db import Database
from selfdevbot.handlers import register
from selfdevbot.scheduler import schedule_all

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

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


def main() -> None:
    cfg = load_config()
    app = Application.builder().token(cfg.telegram_token).post_init(post_init).build()
    app.bot_data["config"] = cfg
    app.bot_data["db"] = Database(cfg.database_path)
    app.bot_data["coach"] = Coach(cfg.openai_api_key, cfg.openai_model, cfg.bot_name)
    register(app, cfg.allowed_user_ids)
    app.run_polling()


if __name__ == "__main__":
    main()
