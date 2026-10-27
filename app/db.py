"""Слой доступа к базе данных SQLite: подключение, схема, миграции."""

from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, List, Optional

from .config import backups_dir, db_path
from .version import APP_NAME

SCHEMA_VERSION = 2

SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    full_name TEXT NOT NULL,
    position TEXT NOT NULL DEFAULT '',
    email TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'supervisor', 'user')),
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ip TEXT,
    user_agent TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    status TEXT NOT NULL DEFAULT 'saved' CHECK (status IN ('saved', 'sent')),
    report_date TEXT NOT NULL,
    person_name TEXT NOT NULL,
    person_position TEXT NOT NULL DEFAULT '',
    purpose TEXT NOT NULL DEFAULT '',
    total_received_cents INTEGER NOT NULL DEFAULT 0,
    total_spent_cents INTEGER NOT NULL DEFAULT 0,
    balance_cents INTEGER NOT NULL DEFAULT 0,
    approved_cents INTEGER NOT NULL DEFAULT 0,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    sent_at TEXT,
    sent_to TEXT,
    email_status TEXT
);
CREATE INDEX IF NOT EXISTS idx_reports_user ON reports(user_id);
CREATE INDEX IF NOT EXISTS idx_reports_date ON reports(report_date);
CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at);

CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor_id INTEGER,
    actor_name TEXT,
    action TEXT NOT NULL,
    entity TEXT,
    entity_id INTEGER,
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
"""

# Сохранённый отчёт изменять нельзя — правило закреплено на уровне базы данных.
SCHEMA_V2 = """
CREATE TRIGGER IF NOT EXISTS reports_immutable
BEFORE UPDATE OF number, user_id, report_date, person_name, person_position, purpose,
    total_received_cents, total_spent_cents, balance_cents, approved_cents, data, created_at
ON reports
BEGIN
    SELECT RAISE(ABORT, 'Сохранённый отчёт нельзя изменить');
END;
"""

MIGRATIONS: Dict[int, str] = {
    1: SCHEMA_V1,
    2: SCHEMA_V2,
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "org_name": 'ООО "Сэйлз Модерн групп"',
    "director_position": "Директор",
    "director_name": "Н.В. Сашко",
    "accountant_position": "Бухгалтер",
    "accountant_name": "",
    "default_recipient": "",
    "purposes": [
        "Командировочные расходы",
        "Расходы на хозяйственные нужды",
    ],
    "smtp": {
        "host": "",
        "port": 587,
        "security": "starttls",  # starttls | ssl | none
        "username": "",
        "password": "",
        "from_email": "",
        "from_name": APP_NAME,
        "subject_prefix": "Авансовый отчёт",
    },
    "session_hours": 12,
    "version_notice": "",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path()), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def session() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query_all(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> List[sqlite3.Row]:
    return list(conn.execute(sql, tuple(params)))


def query_one(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> Optional[sqlite3.Row]:
    return conn.execute(sql, tuple(params)).fetchone()


def get_setting(key: str, default: Any = None) -> Any:
    with session() as conn:
        row = query_one(conn, "SELECT value FROM settings WHERE key = ?", (key,))
    if row is None:
        if key in DEFAULT_SETTINGS:
            return json.loads(json.dumps(DEFAULT_SETTINGS[key]))
        return default
    try:
        return json.loads(row["value"])
    except ValueError:
        return row["value"]


def set_setting(key: str, value: Any) -> None:
    payload = json.dumps(value, ensure_ascii=False)
    with transaction() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, payload),
        )


def all_settings() -> Dict[str, Any]:
    values: Dict[str, Any] = {k: json.loads(json.dumps(v)) for k, v in DEFAULT_SETTINGS.items()}
    with session() as conn:
        for row in query_all(conn, "SELECT key, value FROM settings"):
            try:
                values[row["key"]] = json.loads(row["value"])
            except ValueError:
                values[row["key"]] = row["value"]
    return values


def audit(
    conn: sqlite3.Connection,
    action: str,
    *,
    actor: Optional[sqlite3.Row] = None,
    entity: str = "",
    entity_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    conn.execute(
        "INSERT INTO audit_log (ts, actor_id, actor_name, action, entity, entity_id, details) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            now_iso(),
            actor["id"] if actor is not None else None,
            actor["username"] if actor is not None else None,
            action,
            entity,
            entity_id,
            json.dumps(details or {}, ensure_ascii=False),
        ),
    )


def _current_version(conn: sqlite3.Connection) -> int:
    row = query_one(conn, "SELECT version FROM schema_version")
    if row is None:
        return 0
    return int(row["version"])


def init_db() -> None:
    """Создаёт/обновляет схему. Вызывается при каждом старте приложения."""
    with transaction() as conn:
        conn.executescript(
            "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);"
        )
        current = _current_version(conn)
        if current == 0:
            conn.executescript(SCHEMA_V1)
            conn.execute("DELETE FROM schema_version")
            conn.execute("INSERT INTO schema_version (version) VALUES (1)")
            current = 1
        for version in sorted(MIGRATIONS):
            if version > current:
                conn.executescript(MIGRATIONS[version])
                conn.execute("UPDATE schema_version SET version = ?", (version,))
                current = version
        for key, value in DEFAULT_SETTINGS.items():
            row = query_one(conn, "SELECT 1 FROM settings WHERE key = ?", (key,))
            if row is None:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?)",
                    (key, json.dumps(value, ensure_ascii=False)),
                )


def has_users() -> bool:
    with session() as conn:
        row = query_one(conn, "SELECT COUNT(*) AS c FROM users")
    return bool(row and row["c"])


def next_report_number(conn: sqlite3.Connection, year: int) -> str:
    """Сквозная нумерация отчётов в пределах года, без повторного использования."""
    name = f"report_number_{year}"
    conn.execute(
        "INSERT INTO counters (name, value) VALUES (?, 0) ON CONFLICT(name) DO NOTHING",
        (name,),
    )
    conn.execute("UPDATE counters SET value = value + 1 WHERE name = ?", (name,))
    row = query_one(conn, "SELECT value FROM counters WHERE name = ?", (name,))
    value = int(row["value"]) if row else 1
    return f"АО-{year}-{value:04d}"


def backup_database(reason: str = "manual", keep: int = 20):
    """Копия базы данных. Используется при обновлениях и по кнопке администратора."""
    from pathlib import Path  # локальный импорт, чтобы не плодить зависимости

    target_dir = backups_dir()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = Path(target_dir) / f"avans-{stamp}-{reason}.db"
    with session() as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    shutil.copy2(db_path(), target)
    backups = sorted(target_dir.glob("avans-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in backups[max(1, keep):]:
        try:
            old.unlink()
        except OSError:  # pragma: no cover
            pass
    return target


def ensure_daily_backup() -> None:
    """Раз в сутки делает автоматическую резервную копию базы."""
    from datetime import timedelta

    try:
        existing = sorted(
            backups_dir().glob("avans-*-auto.db"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if existing:
            age = datetime.now() - datetime.fromtimestamp(existing[0].stat().st_mtime)
            if age < timedelta(days=1):
                return
        backup_database(reason="auto")
    except Exception:  # pragma: no cover - резервное копирование не должно ломать старт
        pass
