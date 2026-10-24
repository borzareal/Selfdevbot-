"""Stockage SQLite : profils, check-ins récurrents, rappels ponctuels, historique, mémoire."""

import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id     INTEGER PRIMARY KEY,
    first_name  TEXT,
    profile     TEXT NOT NULL DEFAULT '{}',
    plan_summary TEXT NOT NULL DEFAULT '',
    timezone    TEXT NOT NULL DEFAULT 'Europe/Paris',
    onboarded   INTEGER NOT NULL DEFAULT 0,
    paused      INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS checkins (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id  INTEGER NOT NULL,
    time     TEXT NOT NULL,          -- "HH:MM", heure locale de l'utilisateur
    days     TEXT NOT NULL,          -- JSON, 0 = lundi ... 6 = dimanche
    purpose  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reminders (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id  INTEGER NOT NULL,
    run_at   TEXT NOT NULL,          -- ISO UTC
    text     TEXT NOT NULL,
    sent     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id  INTEGER NOT NULL,
    role     TEXT NOT NULL,
    content  TEXT NOT NULL,
    ts       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id  INTEGER NOT NULL,
    fact     TEXT NOT NULL,
    ts       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    # --- utilisateurs ---------------------------------------------------

    def get_user(self, chat_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
        if not row:
            return None
        user = dict(row)
        user["profile"] = json.loads(user["profile"])
        return user

    def ensure_user(self, chat_id: int, first_name: str | None, default_tz: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO users (chat_id, first_name, timezone, created_at) VALUES (?, ?, ?, ?)",
            (chat_id, first_name, default_tz, _now()),
        )
        self.conn.commit()

    def save_onboarding(self, chat_id: int, profile: dict, tz: str, plan_summary: str) -> None:
        self.conn.execute(
            "UPDATE users SET profile = ?, timezone = ?, plan_summary = ?, onboarded = 1, paused = 0 "
            "WHERE chat_id = ?",
            (json.dumps(profile, ensure_ascii=False), tz, plan_summary, chat_id),
        )
        self.conn.commit()

    def update_profile_field(self, chat_id: int, field: str, value: str) -> None:
        user = self.get_user(chat_id)
        if not user:
            return
        user["profile"][field] = value
        self.conn.execute(
            "UPDATE users SET profile = ? WHERE chat_id = ?",
            (json.dumps(user["profile"], ensure_ascii=False), chat_id),
        )
        self.conn.commit()

    def set_paused(self, chat_id: int, paused: bool) -> None:
        self.conn.execute("UPDATE users SET paused = ? WHERE chat_id = ?", (int(paused), chat_id))
        self.conn.commit()

    def onboarded_users(self) -> list[dict]:
        rows = self.conn.execute("SELECT chat_id FROM users WHERE onboarded = 1").fetchall()
        return [self.get_user(r["chat_id"]) for r in rows]

    def delete_user(self, chat_id: int) -> None:
        for table in ("users", "checkins", "reminders", "messages", "memories"):
            self.conn.execute(f"DELETE FROM {table} WHERE chat_id = ?", (chat_id,))
        self.conn.commit()

    # --- check-ins récurrents -------------------------------------------

    def replace_checkins(self, chat_id: int, checkins: list[dict]) -> None:
        self.conn.execute("DELETE FROM checkins WHERE chat_id = ?", (chat_id,))
        for c in checkins:
            self.conn.execute(
                "INSERT INTO checkins (chat_id, time, days, purpose) VALUES (?, ?, ?, ?)",
                (chat_id, c["time"], json.dumps(c["days"]), c["purpose"]),
            )
        self.conn.commit()

    def add_checkin(self, chat_id: int, time: str, days: list[int], purpose: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO checkins (chat_id, time, days, purpose) VALUES (?, ?, ?, ?)",
            (chat_id, time, json.dumps(days), purpose),
        )
        self.conn.commit()
        return cur.lastrowid

    def remove_checkin(self, chat_id: int, checkin_id: int) -> bool:
        cur = self.conn.execute(
            "DELETE FROM checkins WHERE chat_id = ? AND id = ?", (chat_id, checkin_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def list_checkins(self, chat_id: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM checkins WHERE chat_id = ? ORDER BY time", (chat_id,)
        ).fetchall()
        return [{**dict(r), "days": json.loads(r["days"])} for r in rows]

    # --- rappels ponctuels ----------------------------------------------

    def add_reminder(self, chat_id: int, run_at_utc: datetime, text: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO reminders (chat_id, run_at, text) VALUES (?, ?, ?)",
            (chat_id, run_at_utc.isoformat(), text),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_reminder(self, reminder_id: int) -> dict | None:
        row = self.conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        return dict(row) if row else None

    def pending_reminders(self, chat_id: int | None = None) -> list[dict]:
        sql = "SELECT * FROM reminders WHERE sent = 0"
        args: tuple = ()
        if chat_id is not None:
            sql += " AND chat_id = ?"
            args = (chat_id,)
        rows = self.conn.execute(sql + " ORDER BY run_at", args).fetchall()
        return [dict(r) for r in rows]

    def mark_reminder_sent(self, reminder_id: int) -> None:
        self.conn.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
        self.conn.commit()

    def delete_reminder(self, chat_id: int, reminder_id: int) -> bool:
        cur = self.conn.execute(
            "DELETE FROM reminders WHERE chat_id = ? AND id = ? AND sent = 0", (chat_id, reminder_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    # --- historique & mémoire -------------------------------------------

    def add_message(self, chat_id: int, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO messages (chat_id, role, content, ts) VALUES (?, ?, ?, ?)",
            (chat_id, role, content, _now()),
        )
        self.conn.commit()

    def recent_messages(self, chat_id: int, limit: int = 30) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content, ts FROM messages WHERE chat_id = ? ORDER BY id DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def add_memory(self, chat_id: int, fact: str) -> None:
        self.conn.execute(
            "INSERT INTO memories (chat_id, fact, ts) VALUES (?, ?, ?)", (chat_id, fact, _now())
        )
        self.conn.commit()

    def list_memories(self, chat_id: int, limit: int = 50) -> list[str]:
        rows = self.conn.execute(
            "SELECT fact FROM memories WHERE chat_id = ? ORDER BY id DESC LIMIT ?", (chat_id, limit)
        ).fetchall()
        return [r["fact"] for r in reversed(rows)]
