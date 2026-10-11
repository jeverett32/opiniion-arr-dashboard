# Plotly chart builders — Opiniion brand palette.

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

COLORS = {
    "beginning": "#2A2A2A",
    "opening": "#6B7280",
    "new": "#007A74",
    "expansion": "#00A8A0",
    "contraction": "#D97706",
    "churn": "#D14343",
    "reactivation": "#48C8C0",
    "ending": "#007A74",
    "line": "#00A8A0",
    "grr": "#D14343",
    "nrr": "#00A8A0",
    "grid": "#E8F0EF",
    "paper": "#FFFFFF",
    "font": "#2A2A2A",
    "axis": "#94A3B8",
}


def _money_short(v: float) -> str:
    av = abs(v)
    if av >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if av >= 1_000:
        return f"${v/1_000:.0f}K"
    return f"${v:,.0f}"


def _layout(fig: go.Figure, *, tall: bool = False) -> go.Figure:
    # Titles live in the panel headers — keep Plotly chrome minimal to avoid overlap.
    fig.update_layout(
        title=None,
        paper_bgcolor=COLORS["paper"],
        plot_bgcolor=COLORS["paper"],
        font=dict(family="DM Sans, Segoe UI, sans-serif", color=COLORS["font"], size=12),
        margin=dict(l=56, r=16, t=28 if fig.data and any(getattr(t, "name", None) for t in fig.data) else 12, b=56),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            x=0,
            xanchor="left",
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=11),
            itemclick="toggle",
        ),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="#2A2A2A",
            font_size=12,
            font_family="DM Sans, Segoe UI, sans-serif",
            font_color="#FFFFFF",
            bordercolor="#2A2A2A",
        ),
        height=420 if tall else 360,
        bargap=0.25,
    )
    fig.update_xaxes(
        showgrid=False,
        linecolor=COLORS["axis"],
        tickfont=dict(size=10, color="#6B7280"),
        tickangle=-35,
        automargin=True,
        title_text="",
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor=COLORS["grid"],
        zerolinecolor="#CBD5E1",
        tickfont=dict(size=11, color="#6B7280"),
        automargin=True,
        title_text="",
        separatethousands=True,
    )
    return fig


def waterfall_bridge(row: pd.Series, title: str | None = None) -> go.Figure:
    del title  # panel header owns the title
    all_labels = [
        ("Beginning", "absolute", float(row.get("beginning_arr", 0) or 0), "ARR at start of month"),
        ("Opening", "relative", float(row.get("opening_arr", 0) or 0), "Opening book (first extract month only)"),
        ("New", "relative", float(row.get("new_arr", 0) or 0), "First-time logos"),
        ("Expansion", "relative", float(row.get("expansion_arr", 0) or 0), "Existing customers growing ARR"),
        ("Contraction", "relative", -float(row.get("contraction_arr", 0) or 0), "Existing customers shrinking ARR"),
        ("Churn", "relative", -float(row.get("churn_arr", 0) or 0), "Customers going to $0 ARR"),
        ("Reactivation", "relative", float(row.get("reactivation_arr", 0) or 0), "Return after prior churn"),
        ("Ending", "total", float(row.get("ending_arr", 0) or 0), "ARR at month end"),
    ]
    steps = [
        (lab, meas, val, tip)
        for lab, meas, val, tip in all_labels
        if lab in ("Beginning", "Ending") or abs(val) > 0.01
    ]
    labels = [s[0] for s in steps]
    measures = [s[1] for s in steps]
    values = [s[2] for s in steps]
    tips = [s[3] for s in steps]

    max_abs = max((abs(v) for v in values), default=1) or 1
    texts = []
    for v in values:
        if abs(v) < max_abs * 0.04 or abs(v) < 1:
            texts.append("")
        else:
            texts.append(_money_short(v))

    custom = [f"{lab}<br>{tip}<br><b>${abs(v):,.0f}</b>" for lab, tip, v in zip(labels, tips, values)]
    fig = go.Figure(
        go.Waterfall(
            name="ARR",
            orientation="v",
            measure=measures,
            x=labels,
            y=values,
            text=texts,
            textposition="outside",
            textfont=dict(size=10, color=COLORS["font"]),
            cliponaxis=False,
            customdata=custom,
            hovertemplate="%{customdata}<extra></extra>",
            connector={"line": {"color": "#CBD5E1", "width": 1}},
            increasing={"marker": {"color": COLORS["expansion"]}},
            decreasing={"marker": {"color": COLORS["churn"]}},
            totals={"marker": {"color": COLORS["ending"]}},
        )
    )
    fig = _layout(fig)
    fig.update_layout(margin=dict(l=48, r=16, t=36, b=48), showlegend=False)
    fig.update_xaxes(tickangle=0, tickfont=dict(size=11, color="#6B7280"))
    # Zoom Y-axis to bridge range (matches Excel workbook) so MoM changes are visible.
    beg = float(row.get("beginning_arr", 0) or 0)
    end = float(row.get("ending_arr", 0) or 0)
    exp = float(row.get("expansion_arr", 0) or 0)
    cont = float(row.get("contraction_arr", 0) or 0)
    churn = float(row.get("churn_arr", 0) or 0)
    pad = max(exp, cont, churn, 50_000) * 0.15
    y_lo = min(beg - cont - churn, end) - pad
    y_hi = max(beg + exp, end) + pad
    if y_hi > y_lo:
        fig.update_yaxes(range=[y_lo, y_hi])
    return fig


def ending_arr_trend(bridge: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=bridge["month"],
            y=bridge["ending_arr"],
            mode="lines+markers",
            name="Ending ARR",
            line=dict(color=COLORS["line"], width=2.5, shape="spline"),
            marker=dict(size=5, color=COLORS["line"], line=dict(width=0)),
            fill="tozeroy",
            fillcolor="rgba(0, 168, 160, 0.10)",
            hovertemplate="%{x}<br>Ending ARR: <b>$%{y:,.0f}</b><extra></extra>",
        )
    )
    fig = _layout(fig)
    fig.update_layout(showlegend=False, margin=dict(l=56, r=16, t=12, b=56))
    # Show every 3rd month label to reduce x-axis crowding
    if len(bridge) > 12:
        tickvals = bridge["month"].tolist()[::3]
        fig.update_xaxes(tickmode="array", tickvals=tickvals, ticktext=tickvals)
    return fig


def retention_trend(bridge: pd.DataFrame) -> go.Figure:
    df = bridge.dropna(subset=["ttm_grr"], how="all")
    fig = go.Figure()
    if "ttm_grr" in df.columns and df["ttm_grr"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=df["month"],
                y=df["ttm_grr"],
                mode="lines+markers",
                name="TTM GRR",
                line=dict(color=COLORS["grr"], width=2.2),
                marker=dict(size=5),
                hovertemplate="%{x}<br>GRR: <b>%{y:.1%}</b><br>Gross retention of starting cohort<extra></extra>",
            )
        )
    if "ttm_nrr" in df.columns and df["ttm_nrr"].notna().any():
        fig.add_trace(
            go.Scatter(
                x=df["month"],
                y=df["ttm_nrr"],
                mode="lines+markers",
                name="TTM NRR",
                line=dict(color=COLORS["nrr"], width=2.2),
                marker=dict(size=5),
                hovertemplate="%{x}<br>NRR: <b>%{y:.1%}</b><br>Includes expansion; excludes New/Reactivation<extra></extra>",
            )
        )
    fig = _layout(fig)
    fig.update_yaxes(tickformat=".0%")
    vals = []
    if "ttm_grr" in df.columns:
        vals.extend(df["ttm_grr"].dropna().tolist())
    if "ttm_nrr" in df.columns:
        vals.extend(df["ttm_nrr"].dropna().tolist())
    if vals:
        lo = min(vals)
        hi = max(vals)
        y_min = max(0.0, (int(lo * 10) / 10) - 0.05)
        y_max = (int(hi * 10) + 1) / 10
        if y_max <= hi:
            y_max += 0.1
        fig.update_yaxes(range=[y_min, y_max])
    # Put the 100% guide on the right so it doesn't collide with the legend.
    fig.add_hline(
        y=1.0,
        line_dash="dot",
        line_color="#94A3B8",
        annotation_text="100%",
        annotation_position="top right",
        annotation_font_size=10,
        annotation_font_color="#6B7280",
    )
    fig.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.08, x=0, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=56, r=48, t=40, b=56),
    )
    if len(df) > 12:
        tickvals = df["month"].tolist()[::3]
        fig.update_xaxes(tickmode="array", tickvals=tickvals, ticktext=tickvals)
    return fig


def movement_stacked(bridge: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    series = [
        ("new_arr", "New", COLORS["new"], "First-time customer ARR"),
        ("expansion_arr", "Expansion", COLORS["expansion"], "Growth from existing customers"),
        ("reactivation_arr", "Reactivation", COLORS["reactivation"], "Return after churn"),
        ("contraction_arr", "Contraction", COLORS["contraction"], "Shrink while remaining active"),
        ("churn_arr", "Churn", COLORS["churn"], "Customers to $0 ARR"),
    ]
    for col, name, color, tip in series:
        raw = bridge[col]
        y = raw if col not in ("contraction_arr", "churn_arr") else -raw
        fig.add_trace(
            go.Bar(
                x=bridge["month"],
                y=y,
                name=name,
                marker_color=color,
                customdata=raw,
                hovertemplate=(
                    f"{name}: <b>$%{{customdata:,.0f}}</b><br>{tip}"
                    "<extra></extra>"
                ),
            )
        )
    fig = _layout(fig, tall=True)
    fig.update_layout(
        barmode="relative",
        legend=dict(orientation="h", yanchor="bottom", y=1.06, x=0, bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=56, r=16, t=44, b=56),
    )
    if len(bridge) > 12:
        tickvals = bridge["month"].tolist()[::3]
        fig.update_xaxes(tickmode="array", tickvals=tickvals, ticktext=tickvals)
    return fig


def customer_arr_line(mov: pd.DataFrame, customer_id: str) -> go.Figure:
    sub = mov[mov["customer_id"].astype(str) == str(customer_id)].sort_values("month")
    fig = go.Figure(
        go.Scatter(
            x=sub["month"],
            y=sub["ending_arr"],
            mode="lines+markers",
            name=f"Customer {customer_id}",
            line=dict(color=COLORS["line"], width=2.5, shape="spline"),
            marker=dict(size=5, color=COLORS["line"]),
            fill="tozeroy",
            fillcolor="rgba(0, 168, 160, 0.10)",
            customdata=sub["movement_type"],
            hovertemplate="%{x}<br>ARR: <b>$%{y:,.0f}</b><br>%{customdata}<extra></extra>",
        )
    )
    fig = _layout(fig)
    fig.update_layout(showlegend=False, margin=dict(l=56, r=16, t=12, b=56))
    if len(sub) > 12:
        tickvals = sub["month"].tolist()[::3]
        fig.update_xaxes(tickmode="array", tickvals=tickvals, ticktext=tickvals)
    return fig


def arr_forecast(
    bridge: pd.DataFrame,
    forecast: pd.DataFrame,
    trend: pd.DataFrame | None = None,
) -> go.Figure:
    """Actual ending ARR with scenario forecast and optional trend baseline."""
    fig = go.Figure()
    actual = bridge.copy()
    actual["kind"] = "actual"
    fig.add_trace(
        go.Scatter(
            x=actual["month"],
            y=actual["ending_arr"],
            mode="lines+markers",
            name="Actual",
            line=dict(color=COLORS["line"], width=2.5),
            marker=dict(size=4),
            hovertemplate="%{x}<br>Actual: <b>$%{y:,.0f}</b><extra></extra>",
        )
    )
    if not forecast.empty:
        # Bridge last actual to first forecast point
        bridge_x = [actual["month"].iloc[-1], forecast["month"].iloc[0]]
        bridge_y = [actual["ending_arr"].iloc[-1], forecast["ending_arr"].iloc[0]]
        fig.add_trace(
            go.Scatter(
                x=bridge_x,
                y=bridge_y,
                mode="lines",
                line=dict(color=COLORS["expansion"], width=2, dash="dot"),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=forecast["month"],
                y=forecast["ending_arr"],
                mode="lines+markers",
                name="Scenario forecast",
                line=dict(color=COLORS["expansion"], width=2.5, dash="dash"),
                marker=dict(size=5, symbol="diamond"),
                hovertemplate="%{x}<br>Forecast: <b>$%{y:,.0f}</b><extra></extra>",
            )
        )
    if trend is not None and not trend.empty:
        fig.add_trace(
            go.Scatter(
                x=trend["month"],
                y=trend["ending_arr"],
                mode="lines",
                name="Linear trend",
                line=dict(color="#94A3B8", width=1.5, dash="dot"),
                hovertemplate="%{x}<br>Trend: <b>$%{y:,.0f}</b><extra></extra>",
            )
        )
    fig = _layout(fig, tall=True)
    fig.update_layout(
        margin=dict(l=56, r=16, t=36, b=56),
        legend=dict(orientation="h", yanchor="bottom", y=1.06, x=0),
    )
    # Vertical line at forecast start
    if not forecast.empty:
        fig.add_vline(
            x=actual["month"].iloc[-1],
            line_dash="dash",
            line_color="#CBD5E1",
            line_width=1,
        )
    return fig
