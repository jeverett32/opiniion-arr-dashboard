"""SQLite schema, seed, and rebuild for the ARR dashboard."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from bridge_logic import build_monthly_bridge, build_movements, load_invoices

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "arr.db"
REPO_ROOT = APP_DIR.parent
DEFAULT_SOURCE = REPO_ROOT / "case_materials" / "Analytics Engineer Case Study Data.xlsx"

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS raw_invoices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id TEXT NOT NULL,
    customer_name TEXT,
    industry TEXT NOT NULL,
    sub_industry TEXT NOT NULL,
    month TEXT NOT NULL,
    invoiced_amount REAL NOT NULL DEFAULT 0,
    is_recurring INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(customer_id, month)
);

CREATE TABLE IF NOT EXISTS arr_movements (
    customer_id TEXT NOT NULL,
    month TEXT NOT NULL,
    industry TEXT,
    sub_industry TEXT,
    movement_type TEXT,
    beginning_arr REAL,
    opening_arr REAL,
    new_arr REAL,
    expansion_arr REAL,
    contraction_arr REAL,
    churn_arr REAL,
    reactivation_arr REAL,
    ending_arr REAL,
    PRIMARY KEY (customer_id, month)
);

CREATE TABLE IF NOT EXISTS arr_bridge_monthly (
    month TEXT PRIMARY KEY,
    beginning_arr REAL,
    opening_arr REAL,
    new_arr REAL,
    expansion_arr REAL,
    contraction_arr REAL,
    churn_arr REAL,
    reactivation_arr REAL,
    ending_arr REAL,
    net_new_arr REAL,
    mom_growth_rate REAL,
    beg_arr_ttm_start REAL,
    ttm_grr REAL,
    ttm_nrr REAL,
    active_logos INTEGER,
    new_logos INTEGER,
    churned_logos INTEGER,
    reactivated_logos INTEGER,
    bridge_ties INTEGER,
    beginning_matches_prior_ending INTEGER
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_movements_month ON arr_movements(month);
CREATE INDEX IF NOT EXISTS idx_movements_industry ON arr_movements(industry);
CREATE INDEX IF NOT EXISTS idx_invoices_month ON raw_invoices(month);
"""


def connect(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def rebuild_arr_tables(conn: sqlite3.Connection) -> dict:
    invoices = pd.read_sql_query(
        """
        SELECT customer_id, industry, sub_industry, month,
               invoiced_amount, is_recurring
        FROM raw_invoices
        ORDER BY customer_id, month
        """,
        conn,
    )
    if invoices.empty:
        conn.execute("DELETE FROM arr_movements")
        conn.execute("DELETE FROM arr_bridge_monthly")
        conn.commit()
        return {"months": 0, "customers": 0, "bridge_ties": True}

    mov = build_movements(invoices)
    bridge = build_monthly_bridge(mov)

    mov_cols = [
        "customer_id",
        "month",
        "industry",
        "sub_industry",
        "movement_type",
        "beginning_arr",
        "opening_arr",
        "new_arr",
        "expansion_arr",
        "contraction_arr",
        "churn_arr",
        "reactivation_arr",
        "ending_arr",
    ]
    bridge_cols = [
        "month",
        "beginning_arr",
        "opening_arr",
        "new_arr",
        "expansion_arr",
        "contraction_arr",
        "churn_arr",
        "reactivation_arr",
        "ending_arr",
        "net_new_arr",
        "mom_growth_rate",
        "beg_arr_ttm_start",
        "ttm_grr",
        "ttm_nrr",
        "active_logos",
        "new_logos",
        "churned_logos",
        "reactivated_logos",
        "bridge_ties",
        "beginning_matches_prior_ending",
    ]

    conn.execute("DELETE FROM arr_movements")
    conn.execute("DELETE FROM arr_bridge_monthly")
    mov[mov_cols].to_sql("arr_movements", conn, if_exists="append", index=False)
    bridge[bridge_cols].to_sql("arr_bridge_monthly", conn, if_exists="append", index=False)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('last_rebuild', datetime('now'))"
    )
    conn.commit()
    return {
        "months": int(len(bridge)),
        "customers": int(mov["customer_id"].nunique()),
        "bridge_ties": bool(bridge["bridge_ties"].all()),
        "ending_arr": float(bridge.iloc[-1]["ending_arr"]) if len(bridge) else 0.0,
    }


def seed_from_excel(conn: sqlite3.Connection, source: Path | str = DEFAULT_SOURCE) -> dict:
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(f"Case study extract not found: {source}")

    invoices = load_invoices(source)
    invoices = invoices.rename(columns={})
    seed = invoices[
        ["customer_id", "industry", "sub_industry", "month", "invoiced_amount", "is_recurring"]
    ].copy()
    seed["customer_name"] = seed["customer_id"]

    conn.execute("DELETE FROM raw_invoices")
    seed[
        [
            "customer_id",
            "customer_name",
            "industry",
            "sub_industry",
            "month",
            "invoiced_amount",
            "is_recurring",
        ]
    ].to_sql("raw_invoices", conn, if_exists="append", index=False)
    conn.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES ('seed_source', ?)",
        (str(source),),
    )
    conn.commit()
    return rebuild_arr_tables(conn)


def ensure_db(db_path: Path | str = DB_PATH, source: Path | str = DEFAULT_SOURCE) -> Path:
    """Create schema and seed if the DB is missing or empty."""
    db_path = Path(db_path)
    conn = connect(db_path)
    try:
        init_schema(conn)
        n = conn.execute("SELECT COUNT(*) AS n FROM raw_invoices").fetchone()["n"]
        if n == 0:
            stats = seed_from_excel(conn, source)
            print(f"Seeded arr.db: {stats}")
        else:
            # Ensure derived tables exist / are current
            m = conn.execute("SELECT COUNT(*) AS n FROM arr_bridge_monthly").fetchone()["n"]
            if m == 0:
                stats = rebuild_arr_tables(conn)
                print(f"Rebuilt arr.db: {stats}")
    finally:
        conn.close()
    return db_path


if __name__ == "__main__":
    path = ensure_db()
    conn = connect(path)
    try:
        bridge = pd.read_sql_query(
            "SELECT month, ending_arr, ttm_grr, ttm_nrr, bridge_ties FROM arr_bridge_monthly ORDER BY month",
            conn,
        )
        print(bridge.tail(3).to_string(index=False))
        print(f"DB: {path} ({path.stat().st_size:,} bytes)")
    finally:
        conn.close()
