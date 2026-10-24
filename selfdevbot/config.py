import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    telegram_token: str
    openai_api_key: str
    openai_model: str
    bot_name: str
    default_timezone: str
    allowed_user_ids: frozenset[int]
    database_path: str


def load_config() -> Config:
    missing = [k for k in ("TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY") if not os.getenv(k)]
    if missing:
        raise SystemExit(f"Variables manquantes dans .env : {', '.join(missing)}")

    allowed = frozenset(
        int(x) for x in os.getenv("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x
    )
    return Config(
        telegram_token=os.environ["TELEGRAM_BOT_TOKEN"],
        openai_api_key=os.environ["OPENAI_API_KEY"],
        openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        bot_name=os.getenv("BOT_NAME", "Jarvis"),
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "Europe/Paris"),
        allowed_user_ids=allowed,
        database_path=os.getenv("DATABASE_PATH", "selfdevbot.db"),
    )
