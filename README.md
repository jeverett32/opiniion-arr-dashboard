# Opiniion ARR Bridge Dashboard

Shiny for Python dashboard for the Opiniion case study — ARR bridge, customer drill-down, and forecast views over SQLite.

## Quick start (Docker)

```bash
docker compose up -d --build
open http://127.0.0.1:8000
```

See [DEPLOY.md](DEPLOY.md) for updates, tunnel, and DB seeding.

## Local dev

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python db.py
.venv/bin/shiny run app.py --reload --port 8000
```

## Layout

| Path | Role |
|------|------|
| `app.py` | Shiny UI |
| `db.py` | Schema + seed |
| `bridge_logic.py` | Bridge / TTM metrics |
| `queries.py` | UI queries |
| `components/charts.py` | Plotly charts |
| `data/arr.db` | SQLite (gitignored; seed with `db.py`) |
