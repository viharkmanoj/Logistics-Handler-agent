"""
Database initialization, connection handling, and schema definitions.
Uses SQLite with WAL mode, foreign keys, and atomic transaction handling.
"""

import sqlite3
import os
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

from logistics.config import DEFAULT_DB_PATH, INITIAL_INVENTORY


def get_db_path(custom_path: Optional[str] = None) -> str:
    """Resolve database path, ensuring parent directory exists."""
    path_str = custom_path or DEFAULT_DB_PATH
    db_file = Path(path_str)
    db_file.parent.mkdir(parents=True, exist_ok=True)
    return str(db_file)


def get_connection(db_path: Optional[str] = None) -> sqlite3.Connection:
    """
    Create a configured SQLite connection with row factory, WAL mode,
    and foreign keys enabled.
    """
    resolved_path = get_db_path(db_path)
    conn = sqlite3.connect(resolved_path, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


@contextmanager
def transaction(db_path: Optional[str] = None):
    """
    Context manager for atomic database transactions.
    Automatically commits on success or rolls back on exception.
    """
    conn = get_connection(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE;")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Optional[str] = None) -> None:
    """
    Initialize all database tables and seed baseline inventory if empty.
    Preserves existing inventory across restarts.
    """
    resolved_path = get_db_path(db_path)
    conn = get_connection(resolved_path)
    try:
        with conn:
            # 1. Inventory Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS inventory (
                    product_id TEXT PRIMARY KEY,
                    product_name TEXT UNIQUE NOT NULL COLLATE NOCASE,
                    available_quantity INTEGER NOT NULL CHECK (available_quantity >= 0),
                    reserved_quantity INTEGER NOT NULL DEFAULT 0 CHECK (reserved_quantity >= 0),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 2. Shipments Table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS shipments (
                    shipment_id TEXT PRIMARY KEY,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    product_name TEXT NOT NULL COLLATE NOCASE,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    status TEXT NOT NULL,
                    idempotency_key TEXT UNIQUE,
                    estimated_delivery TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 3. Agent Activity & Feedback Logs
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_activity (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    action TEXT NOT NULL,
                    tool_name TEXT,
                    status TEXT NOT NULL,
                    details TEXT,
                    error_code TEXT,
                    recovery_attempted INTEGER DEFAULT 0,
                    recovery_success INTEGER DEFAULT 0
                );
            """)

            # 4. Idempotency Records
            conn.execute("""
                CREATE TABLE IF NOT EXISTS idempotency_records (
                    idempotency_key TEXT PRIMARY KEY,
                    shipment_id TEXT NOT NULL,
                    response_payload TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Check if inventory needs initial seeding (DO NOT overwrite existing inventory)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) AS count FROM inventory;")
            count = cursor.fetchone()["count"]

            if count == 0:
                for prod_name, qty in INITIAL_INVENTORY.items():
                    prod_id = f"PROD-{prod_name.upper()[:4]}"
                    cursor.execute("""
                        INSERT INTO inventory (product_id, product_name, available_quantity, reserved_quantity)
                        VALUES (?, ?, ?, 0);
                    """, (prod_id, prod_name, qty))
    finally:
        conn.close()
