# F.E.D.O. HUB — изолированный образ (не трогает другие проекты на VPS)
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FEDO_ROLE=hub \
    FEDO_DATA_DIR=/data

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 fedo

COPY requirements-ecosystem.txt ./
RUN pip install --no-cache-dir -r requirements-ecosystem.txt

COPY ecosystem ./ecosystem
COPY core ./core
COPY ai ./ai
COPY config.py ./

RUN mkdir -p /data && chown -R fedo:fedo /app /data
USER fedo

EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8765/api/health || exit 1

CMD ["python", "-m", "ecosystem.backend", "--role", "hub", "--host", "0.0.0.0", "--port", "8765"]
