"""
database/db.py
SQLite database setup and all query functions for the bulk email sender.
"""
import sqlite3
import os
import uuid
from datetime import datetime
from typing import Optional

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database")
DB_PATH = os.path.join(DB_DIR, "email_history.db")


def get_connection() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create tables if they don't exist."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS send_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_at         TEXT    NOT NULL,
            recipient_email TEXT    NOT NULL,
            recipient_name  TEXT,
            subject         TEXT,
            template_used   TEXT,
            status          TEXT    NOT NULL,
            error_message   TEXT,
            campaign_id     TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS csv_progress (
            filename      TEXT PRIMARY KEY,
            total_rows    INTEGER,
            last_sent_row INTEGER,
            updated_at    TEXT
        )
    """)
    conn.commit()
    conn.close()


def new_campaign_id() -> str:
    """Generate a unique campaign ID."""
    return str(uuid.uuid4())


def log_send(
    campaign_id: str,
    email: str,
    name: str,
    subject: str,
    template: str,
    status: str,
    error: str = None,
) -> None:
    """Insert a send record into the database."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO send_history
            (sent_at, recipient_email, recipient_name, subject, template_used, status, error_message, campaign_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(),
            email,
            name,
            subject,
            template,
            status,
            error,
            campaign_id,
        ),
    )
    conn.commit()
    conn.close()


def get_history(limit: int = 500) -> list[dict]:
    """Return the last N send records as a list of dicts."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM send_history ORDER BY id DESC LIMIT ?", (limit,)
    )
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_campaign_stats(campaign_id: str) -> dict:
    """Return sent/failed/skipped counts for a campaign."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT status, COUNT(*) as cnt
        FROM send_history
        WHERE campaign_id = ?
        GROUP BY status
        """,
        (campaign_id,),
    )
    stats = {"sent": 0, "failed": 0, "skipped": 0}
    for row in cursor.fetchall():
        if row["status"] in stats:
            stats[row["status"]] = row["cnt"]
    conn.close()
    return stats


def clear_history() -> None:
    """Delete all send history records."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM send_history")
    conn.commit()
    conn.close()


# ── CSV send-progress tracking ─────────────────────────────────────────────────

def save_progress(filename: str, total_rows: int, last_sent_row: int) -> None:
    """Upsert the sending progress for a CSV file (0-indexed row number)."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO csv_progress (filename, total_rows, last_sent_row, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(filename) DO UPDATE SET
            total_rows    = excluded.total_rows,
            last_sent_row = excluded.last_sent_row,
            updated_at    = excluded.updated_at
        """,
        (filename, total_rows, last_sent_row, datetime.now().isoformat()),
    )
    conn.commit()
    conn.close()


def get_progress(filename: str) -> Optional[dict]:
    """Return progress dict for a filename, or None if not found."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM csv_progress WHERE filename = ?", (filename,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def clear_progress(filename: str) -> None:
    """Delete the progress record for a CSV file."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM csv_progress WHERE filename = ?", (filename,))
    conn.commit()
    conn.close()
