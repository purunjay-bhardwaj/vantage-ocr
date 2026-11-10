"""
SQLite store for seen invoice numbers.
Only stores: normalized invoice number + timestamp.
No names, bank accounts, or file bytes.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings


_DEFAULT = Path(__file__).resolve().parent.parent.parent / "data" / "invoice_store.db"


def _db_path() -> Path:
    return Path(settings.invoice_db_path) if settings.invoice_db_path.strip() else _DEFAULT


def _conn() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute("""
        CREATE TABLE IF NOT EXISTS seen_invoices (
            norm_number TEXT PRIMARY KEY,
            seen_at     TEXT NOT NULL
        )
    """)
    return con


def is_duplicate(norm_number: str) -> bool:
    """Return True if this normalized invoice number was already stored."""
    con = _conn()
    try:
        row = con.execute(
            "SELECT 1 FROM seen_invoices WHERE norm_number = ?", (norm_number,)
        ).fetchone()
    finally:
        con.close()
    return row is not None


def record_invoice(norm_number: str) -> bool:
    """
    Insert the normalized invoice number with current UTC timestamp.
    Returns False if it was already present (lost a race with another request).
    """
    ts = datetime.now(timezone.utc).isoformat()
    con = _conn()
    try:
        cur = con.execute(
            "INSERT OR IGNORE INTO seen_invoices (norm_number, seen_at) VALUES (?, ?)",
            (norm_number, ts),
        )
        con.commit()
        return cur.rowcount == 1
    finally:
        con.close()


def reset_store() -> None:
    """Delete all stored invoice numbers (for testing / demo reset)."""
    con = _conn()
    try:
        con.execute("DELETE FROM seen_invoices")
        con.commit()
    finally:
        con.close()
