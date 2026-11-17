"""SQLite persistence for Umuhinzi AI.

Stores diagnoses, farmer/cooperative registrations and outbreak alerts in the
file selected by `DATABASE_PATH`. Phone numbers and session ids are hashed
before they reach the database, so raw identifiers are never stored.
"""

from __future__ import annotations

import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from app import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS diagnoses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    reporter_hash TEXT,
    pest_id TEXT,
    sector TEXT,
    district TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_diagnoses_pest_sector
    ON diagnoses (pest_id, sector, created_at);

CREATE TABLE IF NOT EXISTS registrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    name TEXT NOT NULL,
    phone_hash TEXT NOT NULL,
    sector TEXT NOT NULL,
    district TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS outbreak_alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pest_id TEXT NOT NULL,
    sector TEXT NOT NULL,
    district TEXT,
    report_count INTEGER NOT NULL,
    threshold INTEGER NOT NULL,
    window_days INTEGER NOT NULL,
    message_rw TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_alerts_pest_sector
    ON outbreak_alerts (pest_id, sector, created_at);
"""

_initialized_paths: set[Path] = set()


def _db_path() -> Path:
    path = Path(config.DB_FILE)
    if not path.is_absolute():
        path = config.BASE_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def hash_identifier(value: str | None) -> str | None:
    """Return a stable SHA-256 hash for a phone number or session id."""
    cleaned = _clean(value)
    if cleaned is None:
        return None
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cutoff_days_ago(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(
        timespec="seconds"
    )


def init_db() -> None:
    """Create the tables and indexes if they do not exist yet."""
    path = _db_path()
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
    _initialized_paths.add(path)


def _ensure_initialized() -> None:
    path = _db_path()
    if path not in _initialized_paths:
        init_db()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    _ensure_initialized()
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def save_diagnosis(
    reporter_hash: str | None,
    pest_id: str | None,
    sector: str | None,
    district: str | None,
    created_at: str | None = None,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO diagnoses
                (reporter_hash, pest_id, sector, district, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                reporter_hash,
                pest_id,
                _clean(sector),
                _clean(district),
                created_at or utc_now(),
            ),
        )
        return int(cursor.lastrowid)


def list_recent_diagnoses(limit: int = 20) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, reporter_hash, pest_id, sector, district, created_at
            FROM diagnoses
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (max(1, limit),),
        ).fetchall()
    return [dict(row) for row in rows]


def count_recent_reports(pest_id: str, sector: str, window_days: int) -> int:
    sector = _clean(sector)
    if not pest_id or not sector:
        return 0
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS report_count
            FROM diagnoses
            WHERE pest_id = ? AND sector = ? AND created_at >= ?
            """,
            (pest_id, sector, cutoff_days_ago(window_days)),
        ).fetchone()
    return int(row["report_count"])


def save_registration(
    role: str,
    name: str,
    phone_hash: str,
    sector: str,
    district: str,
    created_at: str | None = None,
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO registrations
                (role, name, phone_hash, sector, district, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                role,
                name.strip(),
                phone_hash,
                sector.strip(),
                district.strip(),
                created_at or utc_now(),
            ),
        )
        return int(cursor.lastrowid)


def save_alert(
    pest_id: str,
    sector: str,
    district: str | None,
    report_count: int,
    threshold: int,
    window_days: int,
    message_rw: str,
    created_at: str | None = None,
    status: str = "active",
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO outbreak_alerts
                (pest_id, sector, district, report_count, threshold,
                 window_days, message_rw, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pest_id,
                sector,
                _clean(district),
                report_count,
                threshold,
                window_days,
                message_rw,
                status,
                created_at or utc_now(),
            ),
        )
        return int(cursor.lastrowid)


def find_active_alert(
    pest_id: str, sector: str, window_days: int
) -> dict | None:
    sector = _clean(sector)
    if not pest_id or not sector:
        return None
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT *
            FROM outbreak_alerts
            WHERE pest_id = ? AND sector = ? AND status = 'active'
              AND created_at >= ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (pest_id, sector, cutoff_days_ago(window_days)),
        ).fetchone()
    return dict(row) if row is not None else None


def list_alerts(active_only: bool = False, limit: int = 50) -> list[dict]:
    query = "SELECT * FROM outbreak_alerts"
    params: list = []
    if active_only:
        query += " WHERE status = 'active'"
    query += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(max(1, limit))

    with get_connection() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(row) for row in rows]
