# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

WORKDIR /build
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.11-slim AS runtime

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SQLITE_DB_PATH=/app/data/supply_planner_memory.db \
    PORT=8010

RUN groupadd -r supplyplanner && useradd -r -g supplyplanner -d /app -s /sbin/nologin supplyplanner \
    && mkdir -p /app/data && chown -R supplyplanner:supplyplanner /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* && rm -rf /wheels

COPY --chown=supplyplanner:supplyplanner app ./app
COPY --chown=supplyplanner:supplyplanner cli.py ./cli.py

USER supplyplanner
EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8010/api/health')" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
