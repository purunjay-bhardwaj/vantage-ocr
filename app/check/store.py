"""
SQLite store for seen invoice numbers.
Only stores: normalized invoice number + timestamp.
No names, bank accounts, or file bytes.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "invoice_store.db"


def _conn() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(_DB_PATH))
    con.execute("""
        CREATE TABLE IF NOT EXISTS seen_invoices (
            norm_number TEXT PRIMARY KEY,
            seen_at     TEXT NOT NULL
        )
    """)
    con.commit()
    return con


def is_duplicate(norm_number: str) -> bool:
    """Return True if this normalized invoice number was already stored."""
    with _conn() as con:
        row = con.execute(
            "SELECT 1 FROM seen_invoices WHERE norm_number = ?", (norm_number,)
        ).fetchone()
    return row is not None


def record_invoice(norm_number: str) -> None:
    """Insert the normalized invoice number with current UTC timestamp."""
    ts = datetime.now(timezone.utc).isoformat()
    with _conn() as con:
        con.execute(
            "INSERT OR IGNORE INTO seen_invoices (norm_number, seen_at) VALUES (?, ?)",
            (norm_number, ts),
        )
        con.commit()


def reset_store() -> None:
    """Delete all stored invoice numbers (for testing)."""
    with _conn() as con:
        con.execute("DELETE FROM seen_invoices")
        con.commit()
