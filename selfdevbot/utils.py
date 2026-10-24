"""Fonctions pures (heures, jours, validation du plan) — testables sans Telegram ni OpenAI."""

import re
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAY_NAMES = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
ALL_DAYS = list(range(7))
_TIME_RE = re.compile(r"^\s*(\d{1,2})\s*[:hH]\s*(\d{2})?\s*$")


def parse_hhmm(value: str) -> time | None:
    """'7:30', '07:30', '7h30', '7h' -> time(7, 30). None si invalide."""
    m = _TIME_RE.match(str(value))
    if not m:
        return None
    h, mnt = int(m.group(1)), int(m.group(2) or 0)
    if h > 23 or mnt > 59:
        return None
    return time(h, mnt)


def resolve_timezone(name: str | None, default: str) -> str:
    try:
        ZoneInfo(name or "")
        return name
    except (ZoneInfoNotFoundError, ValueError):
        return default


def to_ptb_days(days: list[int]) -> tuple[int, ...]:
    """Nos jours (0 = lundi, comme Python) -> jours python-telegram-bot (0 = dimanche)."""
    return tuple(sorted({(d + 1) % 7 for d in days}))


def format_days(days: list[int]) -> str:
    days = sorted(set(days))
    if days == ALL_DAYS:
        return "tous les jours"
    if days == [0, 1, 2, 3, 4]:
        return "en semaine"
    if days == [5, 6]:
        return "le week-end"
    return ", ".join(DAY_NAMES[d] for d in days)


def clean_days(raw) -> list[int]:
    if not isinstance(raw, list):
        return ALL_DAYS
    days = sorted({int(d) for d in raw if isinstance(d, (int, float, str)) and str(d).isdigit() and 0 <= int(d) <= 6})
    return days or ALL_DAYS


def validate_checkins(raw, max_count: int = 15) -> list[dict]:
    """Nettoie la liste de check-ins renvoyée par le modèle."""
    result = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        t = parse_hhmm(item.get("time", ""))
        purpose = str(item.get("purpose", "")).strip()
        if not t or not purpose:
            continue
        result.append({"time": t.strftime("%H:%M"), "days": clean_days(item.get("days")), "purpose": purpose})
    result.sort(key=lambda c: c["time"])
    return result[:max_count]


def parse_local_datetime(value: str, tz_name: str) -> datetime | None:
    """'2026-10-24T18:30' (heure locale de l'utilisateur) -> datetime UTC aware."""
    try:
        dt = datetime.fromisoformat(value.strip())
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.astimezone(timezone.utc)


def split_message(text: str, limit: int = 4000) -> list[str]:
    """Telegram limite un message à 4096 caractères."""
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks
