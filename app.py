# ARR Bridge Dashboard — Shiny for Python (Opiniion-branded)

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from shiny import reactive, req, ui as core_ui
from shiny.express import input, ui, render
from shinywidgets import render_plotly

from components import charts
from db import ensure_db
from forecast import baseline_components, forecast_arr, score_customers, trend_baseline
from queries import (
    delta_badge,
    get_bridge,
    get_customer_latest,
    get_filter_options,
    get_kpis,
    get_movements,
    money,
    pct,
)

_ = ensure_db()
OPTS = get_filter_options()
MONTHS = OPTS["months"]
DEFAULT_END = MONTHS[-1] if MONTHS else None
DEFAULT_START = MONTHS[0] if MONTHS else None
CUSTOMER_IDS = get_customer_latest()["customer_id"].astype(str).tolist()

KPI_TIPS = {
    "Ending ARR": "Annualized recurring revenue at the selected bridge month (monthly invoice × 12).",
    "TTM GRR": "Trailing-twelve-month Gross Retention for the filtered book. Starting cohort ARR minus contraction and churn, divided by starting ARR.",
    "TTM NRR": "Trailing-twelve-month Net Retention for the filtered book. Includes expansion on the starting cohort; excludes New and Reactivation.",
    "MoM Growth": "Net new ARR in the bridge month divided by beginning ARR.",
    "Active Logos": "Customers with ending ARR > 0 in the bridge month.",
    "Top-10 Conc.": "Share of ending ARR held by the ten largest active customers in the selected bridge month.",
    "Net New ARR": "Opening + New + Expansion + Reactivation − Contraction − Churn for the bridge month.",
}

PANEL_TIPS = {
    "waterfall": "Bridge from beginning ARR to ending ARR for the selected month. Hover each bar for the definition and dollar amount.",
    "trend": "Ending ARR across the full extract window under the current industry filters.",
    "retention": "TTM GRR and NRR for the filtered book — recomputed from movements when industry filters are applied.",
    "movements": "Stacked monthly bridge components. Contraction = downgrade while still active; churn = logo to $0 (only 7 months in this extract, none in Dec 2025).",
    "bridge_table": "Exact monthly bridge rows feeding the charts. bridge_ties = 1 means the identity equation holds.",
    "customers": "Dec 2025 snapshot per customer. “Latest-month movement” is this month’s classification; lifecycle filter finds customers who ever had New/Churn/etc.",
    "customer_detail": "Full 36-month ARR path and movement classification for the selected customer.",
    "forecast": "Project ending ARR using your monthly assumptions. Dashed line = scenario; gray dotted = linear trend on recent history.",
    "signals": "Expansion score from logistic regression on movement history. Churn risk uses contraction/heuristic rules (only 8 churn events in extract — not a production churn model).",
}

_BOOT_BRIDGE = get_bridge()
_BOOT_BASE = baseline_components(_BOOT_BRIDGE) if not _BOOT_BRIDGE.empty else {
    "expansion": 150_000.0,
    "contraction": 75_000.0,
    "churn": 0.0,
    "new": 0.0,
}
_SLIDER_MAX = {
    "expansion": max(int(_BOOT_BRIDGE["expansion_arr"].max() * 2.5), 250_000) if not _BOOT_BRIDGE.empty else 300_000,
    "contraction": max(int(_BOOT_BRIDGE["contraction_arr"].max() * 2.5), 150_000) if not _BOOT_BRIDGE.empty else 200_000,
    "churn": max(int(_BOOT_BRIDGE["churn_arr"].max() * 2.5), 300_000) if not _BOOT_BRIDGE.empty else 300_000,
}


def tip_icon(text: str):
    """Small hoverable ? control (uses core shiny.ui.tooltip)."""
    return core_ui.tooltip(
        core_ui.span("?", class_="tip-icon", tabindex="0"),
        text,
        placement="top",
    )


def panel_heading(title: str, tip: str):
    return ui.div(
        ui.span(title, class_="panel-title"),
        tip_icon(tip),
        class_="panel-title-row",
    )


def labeled_select(id: str, label: str, choices, selected=None, tip: str = ""):
    """Select input with an inline hover tip on the label."""
    label_ui = ui.div(
        ui.span(label),
        tip_icon(tip) if tip else None,
        class_="kpi-label-row",
        style="margin-bottom: 4px;",
    )
    return ui.div(
        label_ui,
        ui.input_select(id, None, choices, selected=selected),
    )


ui.page_opts(
    fillable=True,
    window_title="Opiniion · ARR Bridge",
)

ui.head_content(
    ui.tags.link(rel="icon", type="image/png", href="assets/favicon.png"),
    ui.tags.link(rel="preconnect", href="https://fonts.googleapis.com"),
    ui.tags.link(rel="preconnect", href="https://fonts.gstatic.com", crossorigin=""),
    ui.tags.link(
        rel="stylesheet",
        href="https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;0,9..40,700;1,9..40,400&display=swap",
    ),
    ui.tags.link(rel="stylesheet", href="app.css"),
)

# ----- Brand header -----
with ui.tags.header(class_="app-header"):
    with ui.div(class_="brand-lockup"):
        ui.tags.img(
            src="assets/opiniion-logo.png",
            alt="Opiniion",
            class_="brand-logo",
        )
        ui.div(class_="brand-divider")
        with ui.div(class_="brand-text"):
            ui.span("ARR Bridge", class_="product-name")
            ui.span("Finance · GTM analytics case study", class_="product-tag")
    with ui.div(class_="header-meta"):
        ui.span(
            ui.span(class_="dot"),
            "Live from SQLite bridge",
            class_="meta-pill",
        )
        ui.span(
            tip_icon("36-month customer billing extract. ARR = monthly invoiced × 12."),
            ui.span("Jan 2023 – Dec 2025", style="margin-left:6px;"),
            class_="meta-pill",
        )

with ui.navset_underline(id="main_nav"):

    # ------------------------------------------------------------------ Overview
    with ui.nav_panel("Overview"):
        ui.h2("Overview", class_="page-title")
        ui.p(
            "Company ARR bridge, retention, and concentration — same definitions as the Part 1 workbook.",
            class_="page-sub",
        )

        with ui.div(class_="filter-bar"):
            with ui.layout_columns(col_widths=[4, 4, 4]):
                labeled_select(
                    "ov_industry",
                    "Industry",
                    OPTS["industries"],
                    tip="Filter the book by industry. TTM retention recomputes on the filtered segment.",
                )
                labeled_select(
                    "ov_sub_industry",
                    "Sub-industry",
                    OPTS["sub_industries"],
                    tip="Optional finer cut (e.g. Multi-Family within Property).",
                )
                labeled_select(
                    "ov_month",
                    "Bridge month",
                    {m: m for m in MONTHS},
                    selected=DEFAULT_END,
                    tip="All KPI cards and the waterfall use this month — not fixed to Dec 2025.",
                )

        @reactive.calc
        def ov_kpis():
            return get_kpis(input.ov_industry(), input.ov_sub_industry(), input.ov_month())

        @reactive.calc
        def ov_bridge():
            return get_bridge(input.ov_industry(), input.ov_sub_industry())

        @render.ui
        def ov_kpi_row():
            k = ov_kpis()
            req(k)
            month = k["month"]
            cards = [
                ("Ending ARR", money(k["ending_arr"]), delta_badge(k["ending_arr"], k["prior_ending_arr"])),
                ("TTM GRR", pct(k["ttm_grr"]), f"as of {month}"),
                ("TTM NRR", pct(k["ttm_nrr"]), f"as of {month}"),
                ("MoM Growth", pct(k["mom_growth_rate"]), month),
                (
                    "Active Logos",
                    str(k["active_logos"]),
                    delta_badge(k["active_logos"], k["prior_active_logos"]),
                ),
                ("Top-10 Conc.", pct(k["top10_concentration"]), month),
                ("Net New ARR", money(k["net_new_arr"]), month),
            ]
            bits = []
            for label, value, delta in cards:
                cls = "kpi-delta"
                if isinstance(delta, str) and delta.startswith("▲"):
                    cls += " up"
                elif isinstance(delta, str) and delta.startswith("▼"):
                    cls += " down"
                bits.append(
                    ui.div(
                        ui.div(
                            ui.span(label, class_="kpi-label"),
                            tip_icon(KPI_TIPS[label]),
                            class_="kpi-label-row",
                        ),
                        ui.div(value, class_="kpi-value"),
                        ui.div(delta, class_=cls),
                        class_="kpi-card",
                    )
                )
            return ui.div(*bits, class_="kpi-grid")

        with ui.layout_columns(col_widths=[6, 6]):
            with ui.div(class_="panel-card"):
                panel_heading("Bridge month waterfall", PANEL_TIPS["waterfall"])

                @render_plotly
                def ov_waterfall():
                    bridge = ov_bridge()
                    req(not bridge.empty)
                    month = input.ov_month()
                    row = bridge[bridge["month"] == month]
                    req(not row.empty)
                    return charts.waterfall_bridge(row.iloc[0])

            with ui.div(class_="panel-card"):
                panel_heading("Ending ARR trend", PANEL_TIPS["trend"])

                @render_plotly
                def ov_trend():
                    bridge = ov_bridge()
                    req(not bridge.empty)
                    return charts.ending_arr_trend(bridge)

        with ui.div(class_="panel-card"):
            panel_heading("TTM GRR vs NRR", PANEL_TIPS["retention"])

            @render_plotly
            def ov_retention():
                bridge = ov_bridge()
                req(not bridge.empty)
                return charts.retention_trend(bridge)

    # ------------------------------------------------------------- Bridge Explorer
    with ui.nav_panel("Bridge Explorer"):
        ui.h2("Bridge Explorer", class_="page-title")
        ui.p(
            "Full-period movements with live industry re-aggregation. "
            "Churn is lumpy ($475k total, 7 months) — Oct 2025 alone is $279k. Dec 2025 has contraction only, no churn.",
            class_="page-sub",
        )

        with ui.div(class_="filter-bar"):
            with ui.layout_columns(col_widths=[3, 3, 3, 3]):
                labeled_select(
                    "br_industry",
                    "Industry",
                    OPTS["industries"],
                    tip="Re-sums the bridge from arr_movements for this industry.",
                )
                labeled_select(
                    "br_sub_industry",
                    "Sub-industry",
                    OPTS["sub_industries"],
                    tip="Optional sub-industry cut on the same movement grain.",
                )
                labeled_select(
                    "br_start",
                    "Start month",
                    {m: m for m in MONTHS},
                    selected=DEFAULT_START,
                    tip="Inclusive start of the chart and table window.",
                )
                labeled_select(
                    "br_end",
                    "End month",
                    {m: m for m in MONTHS},
                    selected=DEFAULT_END,
                    tip="Inclusive end of the chart and table window.",
                )

        @reactive.calc
        def br_bridge():
            return get_bridge(
                input.br_industry(),
                input.br_sub_industry(),
                input.br_start(),
                input.br_end(),
            )

        with ui.div(class_="panel-card"):
            panel_heading("Monthly movements", PANEL_TIPS["movements"])

            @render_plotly
            def br_stacked():
                df = br_bridge()
                req(not df.empty)
                return charts.movement_stacked(df)

        with ui.div(class_="panel-card"):
            panel_heading("Bridge table", PANEL_TIPS["bridge_table"])

            @render.data_frame
            def br_table():
                df = br_bridge().copy()
                cols = [
                    "month",
                    "beginning_arr",
                    "opening_arr",
                    "new_arr",
                    "expansion_arr",
                    "contraction_arr",
                    "churn_arr",
                    "reactivation_arr",
                    "ending_arr",
                    "mom_growth_rate",
                    "ttm_grr",
                    "ttm_nrr",
                    "active_logos",
                    "bridge_ties",
                ]
                cols = [c for c in cols if c in df.columns]
                return render.DataGrid(df[cols], height="420px")

    # ----------------------------------------------------------- Customer Explorer
    with ui.nav_panel("Customers"):
        ui.h2("Customers", class_="page-title")
        ui.p(
            "Latest-month (Dec 2025) ARR by customer. Lifecycle filters find customers who ever had New, Churn, etc.",
            class_="page-sub",
        )

        with ui.div(class_="filter-bar"):
            with ui.layout_columns(col_widths=[3, 3, 3, 3]):
                labeled_select(
                    "cu_industry",
                    "Industry",
                    OPTS["industries"],
                    tip="Limit the latest-month customer list by industry.",
                )
                labeled_select(
                    "cu_sub_industry",
                    "Sub-industry",
                    OPTS["sub_industries"],
                    tip="Optional sub-industry filter on the customer list.",
                )
                labeled_select(
                    "cu_movement",
                    "Latest-month movement",
                    [
                        "All",
                        "Expansion",
                        "Contraction",
                        "Flat",
                        "Inactive (ARR = $0)",
                        "No Activity",
                    ],
                    tip="How the customer is classified in Dec 2025. Churned logos show as Inactive or No Activity, not “Churn”.",
                )
                labeled_select(
                    "cu_lifecycle",
                    "Lifecycle event (ever)",
                    [
                        "All",
                        "New",
                        "Churn",
                        "Reactivation",
                        "Opening Balance",
                    ],
                    tip="Customers who ever had this event in the 36-month extract (from Key Events in the workbook).",
                )
            with ui.layout_columns(col_widths=[3, 9]):
                labeled_select(
                    "cu_id",
                    "Customer",
                    {i: f"Customer {i}" for i in CUSTOMER_IDS},
                    selected=CUSTOMER_IDS[0] if CUSTOMER_IDS else None,
                    tip="Customer shown in the trajectory chart and history table.",
                )

        @reactive.calc
        def cu_latest():
            return get_customer_latest(
                input.cu_industry(),
                input.cu_sub_industry(),
                input.cu_movement(),
                input.cu_lifecycle(),
            )

        @reactive.effect
        @reactive.event(
            input.cu_industry,
            input.cu_sub_industry,
            input.cu_movement,
            input.cu_lifecycle,
        )
        def _sync_cu_customer():
            df = cu_latest()
            ids = df["customer_id"].astype(str).tolist()
            choices = {i: f"Customer {i}" for i in ids}
            ui.update_select("cu_id", choices=choices, selected=ids[0] if ids else None)

        with ui.layout_columns(col_widths=[5, 7]):
            with ui.div(class_="panel-card"):
                panel_heading("Customers (latest month)", PANEL_TIPS["customers"])

                @render.data_frame
                def cu_table():
                    df = cu_latest()[
                        ["customer_id", "industry", "sub_industry", "movement_type", "ending_arr"]
                    ].copy()
                    return render.DataGrid(df, height="480px")

            with ui.div(class_="panel-card"):
                panel_heading("Customer detail", PANEL_TIPS["customer_detail"])

                @render_plotly
                def cu_chart():
                    input.cu_industry()
                    input.cu_sub_industry()
                    input.cu_movement()
                    input.cu_lifecycle()
                    cid = input.cu_id()
                    req(cid)
                    mov = get_movements(
                        industry=input.cu_industry(),
                        sub_industry=input.cu_sub_industry(),
                        customer_id=cid,
                    )
                    req(not mov.empty)
                    return charts.customer_arr_line(mov, cid)

                @render.data_frame
                def cu_history():
                    input.cu_industry()
                    input.cu_sub_industry()
                    input.cu_lifecycle()
                    cid = input.cu_id()
                    req(cid)
                    mov = get_movements(
                        industry=input.cu_industry(),
                        sub_industry=input.cu_sub_industry(),
                        customer_id=cid,
                    )
                    cols = [
                        "month",
                        "movement_type",
                        "beginning_arr",
                        "new_arr",
                        "expansion_arr",
                        "contraction_arr",
                        "churn_arr",
                        "reactivation_arr",
                        "ending_arr",
                    ]
                    return render.DataGrid(mov[cols], height="260px")

    # ------------------------------------------------------------------- Predict
    with ui.nav_panel("Predict"):
        ui.h2("Predict", class_="page-title")
        ui.p(
            "Forward-looking ARR scenarios and customer signals from historical movement patterns.",
            class_="page-sub",
        )

        with ui.div(class_="filter-bar"):
            with ui.layout_columns(col_widths=[3, 3, 3, 3]):
                labeled_select(
                    "pr_industry",
                    "Industry",
                    OPTS["industries"],
                    tip="Forecast and scores recompute on the filtered book.",
                )
                labeled_select(
                    "pr_sub_industry",
                    "Sub-industry",
                    OPTS["sub_industries"],
                    tip="Optional segment cut.",
                )
                labeled_select(
                    "pr_horizon",
                    "Forecast horizon",
                    {"3": "3 months", "6": "6 months", "12": "12 months"},
                    selected="6",
                    tip="Months to project beyond Dec 2025.",
                )
                labeled_select(
                    "pr_lookback",
                    "Baseline lookback",
                    {"6": "6 months", "12": "12 months"},
                    selected="12",
                    tip="Trailing window for default monthly $ assumptions.",
                )

        with ui.div(class_="panel-card"):
            panel_heading("Scenario assumptions", PANEL_TIPS["forecast"])
            with ui.layout_columns(col_widths=[3, 3, 3, 3]):
                ui.input_slider(
                    "pr_expansion",
                    "Monthly expansion ($)",
                    min=0,
                    max=_SLIDER_MAX["expansion"],
                    value=int(_BOOT_BASE["expansion"]),
                    step=5_000,
                )
                ui.input_slider(
                    "pr_contraction",
                    "Monthly contraction ($)",
                    min=0,
                    max=_SLIDER_MAX["contraction"],
                    value=int(_BOOT_BASE["contraction"]),
                    step=5_000,
                )
                ui.input_slider(
                    "pr_churn",
                    "Monthly churn ($)",
                    min=0,
                    max=_SLIDER_MAX["churn"],
                    value=int(_BOOT_BASE["churn"]),
                    step=5_000,
                )
                ui.input_slider(
                    "pr_new",
                    "Monthly new logo ARR ($)",
                    min=0,
                    max=50_000,
                    value=int(_BOOT_BASE["new"]),
                    step=1_000,
                )

        @reactive.calc
        def pr_bridge():
            return get_bridge(input.pr_industry(), input.pr_sub_industry())

        @reactive.calc
        def pr_mov():
            return get_movements(input.pr_industry(), input.pr_sub_industry())

        @reactive.calc
        def pr_baseline():
            b = pr_bridge()
            lb = int(input.pr_lookback())
            return baseline_components(b, lb) if not b.empty else _BOOT_BASE

        @reactive.calc
        def pr_forecast_df():
            b = pr_bridge()
            req(not b.empty)
            horizon = int(input.pr_horizon())
            lb = int(input.pr_lookback())
            fc, _ = forecast_arr(
                b,
                horizon,
                expansion_mo=float(input.pr_expansion()),
                contraction_mo=float(input.pr_contraction()),
                churn_mo=float(input.pr_churn()),
                new_mo=float(input.pr_new()),
                lookback=lb,
            )
            return fc

        @reactive.calc
        def pr_trend_df():
            b = pr_bridge()
            req(not b.empty)
            return trend_baseline(b, int(input.pr_horizon()), int(input.pr_lookback()))

        @render.ui
        def pr_baseline_note():
            base = pr_baseline()
            req(base)
            return ui.p(
                f"Reference ({input.pr_lookback()}-mo trailing avg): expansion {money(base['expansion'])}, "
                f"contraction {money(base['contraction'])}, "
                f"churn {money(base['churn'])}, new {money(base['new'])}/mo",
                class_="page-sub",
                style="margin: 0 0 12px;",
            )

        with ui.layout_columns(col_widths=[7, 5]):
            with ui.div(class_="panel-card"):
                panel_heading("ARR forecast", PANEL_TIPS["forecast"])

                @render_plotly
                def pr_chart():
                    b = pr_bridge()
                    fc = pr_forecast_df()
                    req(not b.empty and not fc.empty)
                    return charts.arr_forecast(b, fc, pr_trend_df())

            with ui.div(class_="panel-card"):
                panel_heading("Forecast summary", PANEL_TIPS["forecast"])

                @render.ui
                def pr_summary():
                    b = pr_bridge()
                    fc = pr_forecast_df()
                    req(not b.empty and not fc.empty)
                    cur = float(b.iloc[-1]["ending_arr"])
                    end = float(fc.iloc[-1]["ending_arr"])
                    delta = (end - cur) / cur if cur else 0
                    cards = [
                        ("Current ending ARR", money(cur), str(b.iloc[-1]["month"])),
                        (f"Projected ({input.pr_horizon()} mo)", money(end), fc.iloc[-1]["month"]),
                        ("Implied growth", pct(delta), "vs Dec 2025"),
                        ("Monthly net new", money(float(fc.iloc[0]["net_new_arr"])), "scenario"),
                    ]
                    bits = []
                    for label, value, sub in cards:
                        bits.append(
                            ui.div(
                                ui.div(
                                    ui.span(label, class_="kpi-label"),
                                    class_="kpi-label-row",
                                ),
                                ui.div(value, class_="kpi-value"),
                                ui.div(sub, class_="kpi-delta"),
                                class_="kpi-card",
                            )
                        )
                    return ui.div(*bits, class_="kpi-grid", style="grid-template-columns: 1fr 1fr;")

                @render.data_frame
                def pr_table():
                    fc = pr_forecast_df().copy()
                    cols = [
                        "month",
                        "beginning_arr",
                        "expansion_arr",
                        "contraction_arr",
                        "churn_arr",
                        "net_new_arr",
                        "ending_arr",
                    ]
                    return render.DataGrid(fc[cols], height="220px")

        with ui.div(class_="panel-card"):
            panel_heading("Customer signals", PANEL_TIPS["signals"])
            with ui.layout_columns(col_widths=[4, 4, 4]):
                labeled_select(
                    "pr_sig_filter",
                    "Show",
                    {
                        "all": "All active customers",
                        "risk": "At-risk (Medium + High)",
                        "expand": "Expansion candidates (top quartile score)",
                    },
                    selected="risk",
                    tip="Ranked by churn risk, then expansion propensity.",
                )

            @reactive.calc
            def pr_signals():
                mov = pr_mov()
                req(not mov.empty)
                return score_customers(mov)

            @render.data_frame
            def pr_signal_table():
                df = pr_signals().copy()
                req(not df.empty)
                filt = input.pr_sig_filter()
                if filt == "risk":
                    df = df[df["churn_risk"].isin(["High", "Medium"])]
                elif filt == "expand":
                    df = df[df["expansion_candidate"]]
                show = df[
                    [
                        "customer_id",
                        "industry",
                        "sub_industry",
                        "ending_arr",
                        "churn_risk",
                        "expansion_score",
                        "signal",
                    ]
                ].head(25)
                return render.DataGrid(show, height="420px")

    # --------------------------------------------------------------- Definitions
    with ui.nav_panel("Definitions"):
        ui.h2("Definitions", class_="page-title")
        ui.p(
            "Pinned so Finance, Sales, and CX are looking at the same math.",
            class_="page-sub",
        )
        with ui.div(class_="defn-grid"):
            for title, body in [
                ("ARR", "Monthly invoiced amount × 12. Extract amounts treated as recurring."),
                (
                    "Opening Balance",
                    "Customers already billing in Jan 2023. Seeds the book; not counted as New.",
                ),
                (
                    "New",
                    "First positive ARR after $0 history, with no prior churn. Impact = Ending when Prior is $0.",
                ),
                (
                    "Expansion / Contraction",
                    "MoM ARR change while active. |change| ≤ $0.01 is Flat (float noise).",
                ),
                (
                    "Churn / Reactivation",
                    "Churn = ARR to $0 (Impact negative). Reactivation = return after churn; not New.",
                ),
                (
                    "Bridge identity",
                    "Beginning + Opening + New + Expansion + Reactivation − Contraction − Churn = Ending.",
                ),
                (
                    "TTM GRR / NRR",
                    "12-month window on the filtered book. New and Reactivation excluded from both.",
                ),
                (
                    "2025 note",
                    "Zero new logos in 2025 — growth is expansion on the existing book (see Part 1 workbook).",
                ),
                (
                    "Predict tab",
                    "Scenario forecast uses your monthly $ assumptions on the bridge equation. "
                    "Expansion scores use logistic regression; churn risk is heuristic (small churn sample).",
                ),
            ]:
                with ui.div(class_="defn-item"):
                    ui.tags.dl(
                        ui.tags.dt(title),
                        ui.tags.dd(body),
                    )

    with ui.nav_panel("About"):
        ui.h2("About", class_="page-title")
        with ui.div(class_="panel-card"):
            ui.p(
                "Interactive layer on the Opiniion Analytics Engineer case study. "
                "Numbers come from SQLite (data/arr.db), rebuilt from raw_invoices with the same "
                "classification logic as the Part 1 Excel deliverable."
            )
            ui.tags.ul(
                ui.tags.li("Brand: Opiniion teal (#00A8A0) with official wordmark"),
                ui.tags.li("Stack: Shiny for Python · Plotly · SQLite · scikit-learn"),
                ui.tags.li("Data: 100 customers × 36 months (Jan 2023 – Dec 2025)"),
                ui.tags.li("Rebuild: python db.py (or delete data/arr.db and restart)"),
                class_="about-list",
            )
