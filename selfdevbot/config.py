import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

# Gemini expose une API compatible OpenAI : on garde le même SDK, seule l'adresse change.
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


@dataclass(frozen=True)
class Config:
    telegram_token: str
    ai_api_key: str
    ai_base_url: str | None
    ai_model: str
    json_mode: bool
    ai_fallback_models: tuple[str, ...]
    bot_name: str
    default_timezone: str
    allowed_user_ids: frozenset[int]
    database_path: str


def load_config() -> Config:
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        raise SystemExit("Variable manquante dans .env : TELEGRAM_BOT_TOKEN")

    if os.getenv("GEMINI_API_KEY"):
        api_key, base_url = os.environ["GEMINI_API_KEY"], GEMINI_BASE_URL
        model = os.getenv("AI_MODEL") or "gemini-flash-latest"
        fallbacks = os.getenv("AI_FALLBACK_MODELS") or "gemini-flash-lite-latest,gemini-2.5-flash"
        json_mode = False
    elif os.getenv("OPENAI_API_KEY"):
        api_key, base_url = os.environ["OPENAI_API_KEY"], None
        model = os.getenv("AI_MODEL") or os.getenv("OPENAI_MODEL", "gpt-5-mini")
        fallbacks = os.getenv("AI_FALLBACK_MODELS", "")
        json_mode = True
    else:
        raise SystemExit("Mets GEMINI_API_KEY (gratuit) ou OPENAI_API_KEY dans .env")

    allowed = frozenset(
        int(x) for x in os.getenv("ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x
    )
    return Config(
        telegram_token=os.environ["TELEGRAM_BOT_TOKEN"],
        ai_api_key=api_key,
        ai_base_url=base_url,
        ai_model=model,
        json_mode=json_mode,
        ai_fallback_models=tuple(m.strip() for m in fallbacks.split(",") if m.strip()),
        bot_name=os.getenv("BOT_NAME", "Jarvis"),
        default_timezone=os.getenv("DEFAULT_TIMEZONE", "Europe/Paris"),
        allowed_user_ids=allowed,
        database_path=os.getenv("DATABASE_PATH", "selfdevbot.db"),
    )
