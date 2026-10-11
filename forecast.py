"""Forward-looking ARR forecast and customer signal scoring."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

LOOKBACK_DEFAULT = 12


def baseline_components(bridge: pd.DataFrame, lookback: int = LOOKBACK_DEFAULT) -> dict[str, float]:
    """Trailing monthly averages for scenario defaults."""
    tail = bridge.tail(max(1, lookback))
    return {
        "expansion": float(tail["expansion_arr"].mean()),
        "contraction": float(tail["contraction_arr"].mean()),
        "churn": float(tail["churn_arr"].mean()),
        "new": float(tail["new_arr"].mean()),
        "net_new": float(tail["net_new_arr"].mean()),
    }


def _future_months(last_month: str, horizon: int) -> list[str]:
    start = pd.Timestamp(last_month) + pd.offsets.MonthEnd(1)
    return [(start + pd.offsets.MonthEnd(i)).strftime("%Y-%m-%d") for i in range(horizon)]


def forecast_arr(
    bridge: pd.DataFrame,
    horizon: int = 6,
    *,
    expansion_mo: float | None = None,
    contraction_mo: float | None = None,
    churn_mo: float | None = None,
    new_mo: float | None = None,
    lookback: int = LOOKBACK_DEFAULT,
) -> tuple[pd.DataFrame, dict[str, float]]:
    """
    Project ending ARR forward using user or trailing-average bridge components.
    Returns (forecast rows, defaults used).
    """
    if bridge.empty or horizon < 1:
        return pd.DataFrame(), {}

    defaults = baseline_components(bridge, lookback)
    exp = defaults["expansion"] if expansion_mo is None else float(expansion_mo)
    cont = defaults["contraction"] if contraction_mo is None else float(contraction_mo)
    churn = defaults["churn"] if churn_mo is None else float(churn_mo)
    new = defaults["new"] if new_mo is None else float(new_mo)

    last = bridge.iloc[-1]
    beginning = float(last["ending_arr"])
    rows: list[dict] = []

    for month in _future_months(str(last["month"]), horizon):
        net_new = new + exp - cont - churn
        ending = beginning + net_new
        rows.append(
            {
                "month": month,
                "beginning_arr": round(beginning, 2),
                "new_arr": round(new, 2),
                "expansion_arr": round(exp, 2),
                "contraction_arr": round(cont, 2),
                "churn_arr": round(churn, 2),
                "net_new_arr": round(net_new, 2),
                "ending_arr": round(ending, 2),
                "kind": "forecast",
            }
        )
        beginning = ending

    used = {"expansion": exp, "contraction": cont, "churn": churn, "new": new}
    return pd.DataFrame(rows), used


def trend_baseline(bridge: pd.DataFrame, horizon: int = 6, lookback: int = LOOKBACK_DEFAULT) -> pd.DataFrame:
    """Simple linear trend on ending ARR for comparison band."""
    if bridge.empty or horizon < 1:
        return pd.DataFrame()

    tail = bridge.tail(max(3, lookback)).copy()
    y = tail["ending_arr"].to_numpy(dtype=float)
    x = np.arange(len(y), dtype=float)
    if len(y) < 2:
        slope = 0.0
        intercept = float(y[-1])
    else:
        slope, intercept = np.polyfit(x, y, 1)

    last_month = str(bridge.iloc[-1]["month"])
    last_x = len(y) - 1
    rows = []
    for i, month in enumerate(_future_months(last_month, horizon), start=1):
        pred = intercept + slope * (last_x + i)
        rows.append({"month": month, "ending_arr": round(max(0.0, pred), 2), "kind": "trend"})
    return pd.DataFrame(rows)


def _training_frame(mov: pd.DataFrame) -> pd.DataFrame:
    """Customer-month rows with next-month expansion label."""
    mov = mov.sort_values(["customer_id", "month"]).copy()
    parts = []
    for _, g in mov.groupby("customer_id", sort=False):
        g = g.sort_values("month").reset_index(drop=True)
        if len(g) < 2:
            continue
        active = g[g["ending_arr"] > 0].copy()
        if active.empty:
            continue
        active["next_expansion"] = (
            g["expansion_arr"].shift(-1).reindex(active.index).fillna(0) > 0
        ).astype(int)
        active["next_contraction"] = (
            g["contraction_arr"].shift(-1).reindex(active.index).fillna(0) > 0
        ).astype(int)
        parts.append(active)
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts, ignore_index=True)


def _customer_features_at(mov: pd.DataFrame, as_of: str) -> pd.DataFrame:
    """Feature row per active customer at as_of month."""
    mov = mov.sort_values(["customer_id", "month"]).copy()
    hist = mov[mov["month"] <= as_of]
    snap = hist[hist["month"] == as_of]
    snap = snap[snap["ending_arr"] > 0].copy()
    if snap.empty:
        return pd.DataFrame()

    rows = []
    for _, row in snap.iterrows():
        cid = row["customer_id"]
        g = hist[hist["customer_id"] == cid].sort_values("month")
        tail6 = g.tail(6)
        tail3 = g.tail(3)
        peak6 = float(tail6["ending_arr"].max()) if len(tail6) else float(row["ending_arr"])
        cur = float(row["ending_arr"])
        contr6 = int((tail6["contraction_arr"] > 0).sum())
        exp6 = int((tail6["expansion_arr"] > 0).sum())
        exp12 = int((g.tail(12)["expansion_arr"] > 0).sum())
        months_since_exp = 0
        for _, r in g.iloc[::-1].iterrows():
            if r["expansion_arr"] > 0:
                break
            months_since_exp += 1
        arr_chg_3m = 0.0
        if len(tail3) >= 2 and float(tail3.iloc[0]["ending_arr"]) > 0:
            arr_chg_3m = (cur - float(tail3.iloc[0]["ending_arr"])) / float(tail3.iloc[0]["ending_arr"])

        rows.append(
            {
                "customer_id": str(cid),
                "industry": row["industry"],
                "sub_industry": row["sub_industry"],
                "ending_arr": cur,
                "is_property": 1 if row["industry"] == "Property" else 0,
                "log_arr": np.log1p(cur),
                "contractions_6m": contr6,
                "expansions_6m": exp6,
                "expansions_12m": exp12,
                "months_since_expansion": months_since_exp,
                "arr_change_3m": arr_chg_3m,
                "decline_from_6m_peak": (peak6 - cur) / peak6 if peak6 > 0 else 0.0,
            }
        )
    return pd.DataFrame(rows)


def _churn_risk_tier(row: pd.Series) -> str:
    if row["contractions_6m"] >= 2 or row["decline_from_6m_peak"] >= 0.15:
        return "High"
    if row["contractions_6m"] >= 1 or row["arr_change_3m"] < -0.02:
        return "Medium"
    return "Low"


def _risk_driver(row: pd.Series) -> str:
    drivers = []
    if row["contractions_6m"] >= 2:
        drivers.append(f"{int(row['contractions_6m'])} contractions in 6 mo")
    elif row["contractions_6m"] == 1:
        drivers.append("1 contraction in 6 mo")
    if row["decline_from_6m_peak"] >= 0.10:
        drivers.append(f"{row['decline_from_6m_peak']:.0%} below 6-mo peak")
    if row["months_since_expansion"] >= 12:
        drivers.append("no expansion in 12+ mo")
    if row["arr_change_3m"] < -0.05:
        drivers.append(f"ARR down {abs(row['arr_change_3m']):.0%} in 3 mo")
    if not drivers:
        if row["expansions_6m"] >= 2:
            drivers.append("repeat expander")
        elif row["expansions_6m"] >= 1:
            drivers.append("recent expansion")
        else:
            drivers.append("stable account")
    return "; ".join(drivers[:2])


def score_customers(mov: pd.DataFrame, as_of: str | None = None) -> pd.DataFrame:
    """
    Rank active customers: expansion propensity (logistic regression) + churn risk tier (heuristics).
    """
    if mov.empty:
        return pd.DataFrame()

    as_of = as_of or str(mov["month"].max())
    features = _customer_features_at(mov, as_of)
    if features.empty:
        return pd.DataFrame()

    train = _training_frame(mov)
    feature_cols = [
        "log_arr",
        "is_property",
        "contractions_6m",
        "expansions_6m",
        "expansions_12m",
        "months_since_expansion",
        "arr_change_3m",
        "decline_from_6m_peak",
    ]

    expansion_score = np.full(len(features), 0.35)
    if len(train) >= 30 and train["next_expansion"].nunique() > 1:
        train_feat = []
        for _, row in train.iterrows():
            cid = row["customer_id"]
            g = mov[mov["customer_id"] == cid].sort_values("month")
            g = g[g["month"] <= row["month"]]
            tail6 = g.tail(6)
            tail3 = g.tail(3)
            peak6 = float(tail6["ending_arr"].max()) if len(tail6) else float(row["ending_arr"])
            cur = float(row["ending_arr"])
            arr_chg_3m = 0.0
            if len(tail3) >= 2 and float(tail3.iloc[0]["ending_arr"]) > 0:
                arr_chg_3m = (cur - float(tail3.iloc[0]["ending_arr"])) / float(tail3.iloc[0]["ending_arr"])
            months_since_exp = 0
            for _, r in g.iloc[::-1].iterrows():
                if r["expansion_arr"] > 0:
                    break
                months_since_exp += 1
            train_feat.append(
                {
                    "log_arr": np.log1p(cur),
                    "is_property": 1 if row["industry"] == "Property" else 0,
                    "contractions_6m": int((tail6["contraction_arr"] > 0).sum()),
                    "expansions_6m": int((tail6["expansion_arr"] > 0).sum()),
                    "expansions_12m": int((g.tail(12)["expansion_arr"] > 0).sum()),
                    "months_since_expansion": months_since_exp,
                    "arr_change_3m": arr_chg_3m,
                    "decline_from_6m_peak": (peak6 - cur) / peak6 if peak6 > 0 else 0.0,
                    "next_expansion": int(row["next_expansion"]),
                }
            )
        train_df = pd.DataFrame(train_feat)
        X = train_df[feature_cols].to_numpy()
        y = train_df["next_expansion"].to_numpy()
        scaler = StandardScaler()
        Xs = scaler.fit_transform(X)
        model = LogisticRegression(max_iter=500, class_weight="balanced")
        model.fit(Xs, y)
        Xp = scaler.transform(features[feature_cols].to_numpy())
        expansion_score = model.predict_proba(Xp)[:, 1]

    out = features.copy()
    out["expansion_score"] = np.round(expansion_score, 3)
    out["churn_risk"] = out.apply(_churn_risk_tier, axis=1)
    out["signal"] = out.apply(_risk_driver, axis=1)
    out["expansion_candidate"] = out["expansion_score"] >= np.quantile(out["expansion_score"], 0.75)
    out = out.sort_values(["churn_risk", "expansion_score"], ascending=[True, False])
    risk_order = {"High": 0, "Medium": 1, "Low": 2}
    out["_risk_sort"] = out["churn_risk"].map(risk_order)
    out = out.sort_values(["_risk_sort", "expansion_score"], ascending=[True, False]).drop(
        columns=["_risk_sort", "is_property", "log_arr"], errors="ignore"
    )
    return out.reset_index(drop=True)
