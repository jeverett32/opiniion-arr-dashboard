FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bridge_logic.py db.py queries.py forecast.py app.py ./
COPY components ./components
COPY www ./www
COPY docker-entrypoint.sh /docker-entrypoint.sh

# Prebuilt SQLite seed (case extract already processed)
COPY data/arr.db /app/data-seed/arr.db

RUN chmod +x /docker-entrypoint.sh \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app /docker-entrypoint.sh

USER appuser
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8000/ >/dev/null || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["shiny", "run", "app.py", "--host", "0.0.0.0", "--port", "8000"]
