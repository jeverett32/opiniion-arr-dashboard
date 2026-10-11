"""ARR bridge classification and aggregation — single source of truth for the app."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

FLAT_TOLERANCE = 0.01


def load_invoices(path: Path | str) -> pd.DataFrame:
    path = Path(path)
    raw = pd.read_excel(path, header=None)
    header_row = raw.index[raw.iloc[:, 1].astype(str).str.contains("Customer Name", na=False)][0]
    header = raw.iloc[header_row].tolist()
    data = raw.iloc[header_row + 1 :].copy()
    data.columns = header
    data = data.dropna(how="all")

    id_col = data.columns[1]
    sub_col = data.columns[2]
    ind_col = data.columns[3]
    month_cols = [c for c in data.columns[4:] if pd.notna(c)]
    data = data[pd.to_numeric(data[id_col], errors="coerce").notna()].copy()

    long = data.melt(
        id_vars=[id_col, sub_col, ind_col],
        value_vars=month_cols,
        var_name="month",
        value_name="invoiced_amount",
    ).rename(columns={id_col: "customer_id", sub_col: "sub_industry", ind_col: "industry"})

    long["customer_id"] = long["customer_id"].astype(int).astype(str)
    long["month"] = pd.to_datetime(long["month"]).dt.strftime("%Y-%m-%d")
    long["invoiced_amount"] = pd.to_numeric(long["invoiced_amount"], errors="coerce").fillna(0.0)
    long["industry"] = long["industry"].astype(str).str.strip()
    long["sub_industry"] = long["sub_industry"].astype(str).str.strip()
    long["is_recurring"] = 1
    return long.sort_values(["customer_id", "month"]).reset_index(drop=True)


def classify_customer(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("month").copy()
    arr = g["arr"].to_numpy(dtype=float)
    beginning = np.concatenate([[0.0], arr[:-1]])
    ending = arr
    delta = ending - beginning

    ever_churned = False
    types, opening, new, expansion, contraction, churn, reactivation = (
        [],
        [],
        [],
        [],
        [],
        [],
        [],
    )

    for i, (beg, end, d) in enumerate(zip(beginning, ending, delta)):
        o = n = e = c = ch = r = 0.0
        if i == 0:
            if end > 0:
                mtype, o = "Opening Balance", float(end)
            else:
                mtype = "No Activity"
        elif beg == 0 and end == 0:
            mtype = "No Activity"
        elif beg == 0 and end > 0:
            if ever_churned:
                mtype, r = "Reactivation", float(end)
            else:
                mtype, n = "New", float(end)
        elif beg > 0 and end == 0:
            mtype, ch = "Churn", float(beg)
            ever_churned = True
        elif abs(d) <= FLAT_TOLERANCE:
            mtype = "Flat"
        elif d > 0:
            mtype, e = "Expansion", float(d)
        else:
            mtype, c = "Contraction", float(abs(d))

        types.append(mtype)
        opening.append(o)
        new.append(n)
        expansion.append(e)
        contraction.append(c)
        churn.append(ch)
        reactivation.append(r)

    g = g.copy()
    g["beginning_arr"] = beginning.round(2)
    g["ending_arr"] = ending.round(2)
    g["movement_type"] = types
    g["opening_arr"] = np.round(opening, 2)
    g["new_arr"] = np.round(new, 2)
    g["expansion_arr"] = np.round(expansion, 2)
    g["contraction_arr"] = np.round(contraction, 2)
    g["churn_arr"] = np.round(churn, 2)
    g["reactivation_arr"] = np.round(reactivation, 2)
    return g


def build_movements(invoices: pd.DataFrame) -> pd.DataFrame:
    inv = invoices.copy()
    if "arr" not in inv.columns:
        recurring = inv.get("is_recurring", 1)
        inv["arr"] = np.where(recurring == 1, inv["invoiced_amount"] * 12.0, 0.0)
    inv["arr"] = inv["arr"].round(2)

    parts = [classify_customer(g) for _, g in inv.groupby("customer_id", sort=False)]
    mov = pd.concat(parts, ignore_index=True)

    calc = (
        mov["beginning_arr"]
        + mov["opening_arr"]
        + mov["new_arr"]
        + mov["expansion_arr"]
        + mov["reactivation_arr"]
        - mov["contraction_arr"]
        - mov["churn_arr"]
    )
    if not np.isclose(calc, mov["ending_arr"], atol=0.02, rtol=0).all():
        raise AssertionError("Customer-month bridge identity failed")
    return mov


def build_monthly_bridge(mov: pd.DataFrame) -> pd.DataFrame:
    agg = (
        mov.groupby("month", as_index=False)
        .agg(
            beginning_arr=("beginning_arr", "sum"),
            opening_arr=("opening_arr", "sum"),
            new_arr=("new_arr", "sum"),
            expansion_arr=("expansion_arr", "sum"),
            contraction_arr=("contraction_arr", "sum"),
            churn_arr=("churn_arr", "sum"),
            reactivation_arr=("reactivation_arr", "sum"),
            ending_arr=("ending_arr", "sum"),
            active_logos=("ending_arr", lambda s: int((s > 0).sum())),
            new_logos=("movement_type", lambda s: int((s == "New").sum())),
            churned_logos=("movement_type", lambda s: int((s == "Churn").sum())),
            reactivated_logos=("movement_type", lambda s: int((s == "Reactivation").sum())),
        )
        .sort_values("month")
        .reset_index(drop=True)
    )

    for col in [
        "beginning_arr",
        "opening_arr",
        "new_arr",
        "expansion_arr",
        "contraction_arr",
        "churn_arr",
        "reactivation_arr",
        "ending_arr",
    ]:
        agg[col] = agg[col].round(2)

    calc_end = (
        agg["beginning_arr"]
        + agg["opening_arr"]
        + agg["new_arr"]
        + agg["expansion_arr"]
        + agg["reactivation_arr"]
        - agg["contraction_arr"]
        - agg["churn_arr"]
    )
    agg["bridge_ties"] = np.isclose(calc_end, agg["ending_arr"], atol=0.05, rtol=0).astype(int)
    prior = agg["ending_arr"].shift(1)
    agg["beginning_matches_prior_ending"] = np.where(
        prior.isna(),
        1,
        np.isclose(agg["beginning_arr"], prior, atol=0.05, rtol=0).astype(int),
    )
    agg["net_new_arr"] = (
        agg["opening_arr"]
        + agg["new_arr"]
        + agg["expansion_arr"]
        + agg["reactivation_arr"]
        - agg["contraction_arr"]
        - agg["churn_arr"]
    ).round(2)
    agg["mom_growth_rate"] = np.where(
        agg["beginning_arr"] > 0,
        agg["net_new_arr"] / agg["beginning_arr"],
        np.nan,
    )

    grr, nrr, denom = [], [], []
    for i in range(len(agg)):
        if i < 11:
            grr.append(np.nan)
            nrr.append(np.nan)
            denom.append(np.nan)
            continue
        window = agg.iloc[i - 11 : i + 1]
        d = float(window.iloc[0]["beginning_arr"])
        if d == 0:
            d = float(window.iloc[0]["beginning_arr"] + window.iloc[0]["opening_arr"])
        denom.append(d if d > 0 else np.nan)
        if d <= 0:
            grr.append(np.nan)
            nrr.append(np.nan)
            continue
        ttm_exp = window["expansion_arr"].sum()
        ttm_cont = window["contraction_arr"].sum()
        ttm_churn = window["churn_arr"].sum()
        grr.append((d - ttm_cont - ttm_churn) / d)
        nrr.append((d + ttm_exp - ttm_cont - ttm_churn) / d)

    agg["beg_arr_ttm_start"] = denom
    agg["ttm_grr"] = grr
    agg["ttm_nrr"] = nrr
    return agg
