# python:3.12.13-slim-trixie multi-architecture manifest (checked 2026-07-10).
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf AS wheels

ENV PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock requirements.txt ./
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.lock

FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
# Security packages are upgraded out of the pinned base image on purpose. Debian
# has fixed releases available before the corresponding python:3.12-slim digest
# has been rebuilt. Keep this list aligned with the daily runtime-image scan and
# remove entries once a newer pinned base already contains the fixed release.
RUN apt-get update \
    && apt-get install -y --no-install-recommends --only-upgrade \
        util-linux \
        openssl \
        libssl3t64 \
        openssl-provider-legacy \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system nexusreach \
    && useradd --system --gid nexusreach --home-dir /app nexusreach

COPY --from=wheels /wheels /wheels
COPY requirements.lock .
RUN pip install --no-index --find-links=/wheels -r requirements.lock \
    && rm -rf /wheels

COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts
RUN chown -R nexusreach:nexusreach /app

USER nexusreach
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
