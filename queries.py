"""Read helpers for the Shiny dashboard."""

from __future__ import annotations

import pandas as pd

from bridge_logic import build_monthly_bridge
from db import DB_PATH, connect, ensure_db


def _conn():
    ensure_db(DB_PATH)
    return connect(DB_PATH)


def filter_clause(industry: str | None, sub_industry: str | None) -> tuple[str, list]:
    clauses = ["1=1"]
    params: list = []
    if industry and industry != "All":
        clauses.append("industry = ?")
        params.append(industry)
    if sub_industry and sub_industry != "All":
        clauses.append("sub_industry = ?")
        params.append(sub_industry)
    return " AND ".join(clauses), params


def get_filter_options() -> dict:
    with _conn() as conn:
        industries = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT industry FROM arr_movements ORDER BY industry"
            ).fetchall()
        ]
        subs = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT sub_industry FROM arr_movements ORDER BY sub_industry"
            ).fetchall()
        ]
        months = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT month FROM arr_bridge_monthly ORDER BY month"
            ).fetchall()
        ]
    return {"industries": ["All"] + industries, "sub_industries": ["All"] + subs, "months": months}


def get_bridge(
    industry: str | None = "All",
    sub_industry: str | None = "All",
    start_month: str | None = None,
    end_month: str | None = None,
) -> pd.DataFrame:
    """Monthly bridge. Re-aggregates from movements when industry filters are applied."""
    if (not industry or industry == "All") and (not sub_industry or sub_industry == "All"):
        with _conn() as conn:
            df = pd.read_sql_query(
                "SELECT * FROM arr_bridge_monthly ORDER BY month",
                conn,
            )
    else:
        mov = get_movements(industry=industry, sub_industry=sub_industry)
        df = build_monthly_bridge(mov) if not mov.empty else pd.DataFrame()

    if start_month:
        df = df[df["month"] >= start_month]
    if end_month:
        df = df[df["month"] <= end_month]
    return df.reset_index(drop=True)


def get_movements(
    industry: str | None = "All",
    sub_industry: str | None = "All",
    movement_type: str | None = "All",
    month: str | None = None,
    customer_id: str | None = None,
) -> pd.DataFrame:
    where, params = filter_clause(industry, sub_industry)
    if movement_type and movement_type != "All":
        where += " AND movement_type = ?"
        params.append(movement_type)
    if month:
        where += " AND month = ?"
        params.append(month)
    if customer_id:
        where += " AND customer_id = ?"
        params.append(customer_id)
    sql = f"SELECT * FROM arr_movements WHERE {where} ORDER BY month, customer_id"
    with _conn() as conn:
        return pd.read_sql_query(sql, conn, params=params)


def get_customer_latest(
    industry: str | None = "All",
    sub_industry: str | None = "All",
    movement_type: str | None = "All",
    lifecycle_event: str | None = "All",
    month: str | None = None,
) -> pd.DataFrame:
    """Customer snapshot for a month (defaults to latest) with optional filters."""
    if not month:
        with _conn() as conn:
            month = conn.execute("SELECT MAX(month) FROM arr_movements").fetchone()[0]

    where, params = filter_clause(industry, sub_industry)
    params = [month] + params

    if movement_type == "Inactive (ARR = $0)":
        where += " AND ending_arr = 0"
    elif movement_type and movement_type not in ("All", ""):
        where += " AND movement_type = ?"
        params.append(movement_type)

    sql = f"""
        SELECT customer_id, industry, sub_industry, movement_type,
               beginning_arr, ending_arr,
               opening_arr, new_arr, expansion_arr, contraction_arr,
               churn_arr, reactivation_arr, month
        FROM arr_movements
        WHERE month = ? AND {where}
        ORDER BY ending_arr DESC
    """
    with _conn() as conn:
        df = pd.read_sql_query(sql, conn, params=params)

    if lifecycle_event and lifecycle_event not in ("All", ""):
        event_ids = _customers_with_lifecycle_event(lifecycle_event, industry, sub_industry)
        df = df[df["customer_id"].astype(str).isin(event_ids)]

    return df.reset_index(drop=True)


def _customers_with_lifecycle_event(
    event: str,
    industry: str | None = "All",
    sub_industry: str | None = "All",
) -> set[str]:
    """Customer IDs that ever had a New / Churn / Reactivation / Opening Balance event."""
    where, params = filter_clause(industry, sub_industry)
    where += " AND movement_type = ?"
    params.append(event)
    sql = f"SELECT DISTINCT customer_id FROM arr_movements WHERE {where}"
    with _conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return {str(r[0]) for r in rows}


def get_kpis(
    industry: str | None = "All",
    sub_industry: str | None = "All",
    month: str | None = None,
) -> dict:
    bridge = get_bridge(industry, sub_industry)
    if bridge.empty:
        return {}
    if month:
        hit = bridge[bridge["month"] == month]
        if hit.empty:
            return {}
        idx = hit.index[0]
        latest = bridge.loc[idx]
        prior = bridge.loc[idx - 1] if idx > bridge.index[0] else latest
    else:
        latest = bridge.iloc[-1]
        prior = bridge.iloc[-2] if len(bridge) > 1 else latest

    snap_month = latest["month"]
    customers = get_customer_latest(industry, sub_industry, month=snap_month)
    active = customers[customers["ending_arr"] > 0]
    top10_pct = (
        float(active.nlargest(10, "ending_arr")["ending_arr"].sum() / active["ending_arr"].sum())
        if len(active) and active["ending_arr"].sum() > 0
        else 0.0
    )
    return {
        "month": snap_month,
        "ending_arr": float(latest["ending_arr"]),
        "prior_ending_arr": float(prior["ending_arr"]),
        "ttm_grr": None if pd.isna(latest.get("ttm_grr")) else float(latest["ttm_grr"]),
        "ttm_nrr": None if pd.isna(latest.get("ttm_nrr")) else float(latest["ttm_nrr"]),
        "mom_growth_rate": None
        if pd.isna(latest.get("mom_growth_rate"))
        else float(latest["mom_growth_rate"]),
        "active_logos": int(latest["active_logos"]),
        "prior_active_logos": int(prior["active_logos"]),
        "top10_concentration": top10_pct,
        "new_arr": float(latest["new_arr"]),
        "expansion_arr": float(latest["expansion_arr"]),
        "contraction_arr": float(latest["contraction_arr"]),
        "churn_arr": float(latest["churn_arr"]),
        "opening_arr": float(latest.get("opening_arr", 0) or 0),
        "reactivation_arr": float(latest["reactivation_arr"]),
        "beginning_arr": float(latest["beginning_arr"]),
        "net_new_arr": float(latest.get("net_new_arr", 0) or 0),
    }


def money(v: float | None) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"${v:,.0f}"


def pct(v: float | None) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:.1%}"


def delta_badge(current: float, prior: float, as_pct: bool = False) -> str:
    if prior == 0:
        return ""
    change = (current - prior) / abs(prior) if not as_pct else (current - prior)
    arrow = "▲" if change >= 0 else "▼"
    if as_pct:
        return f"{arrow} {change:+.1%} pts vs prior"
    return f"{arrow} {change:+.1%} vs prior"
