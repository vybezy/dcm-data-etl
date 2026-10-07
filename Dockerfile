# ---------- Build stage: compile dependencies that need a C compiler ----------
FROM python:3.11-slim-bookworm AS builder

# gcc and the PostgreSQL headers are only needed to compile psycopg2
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


# ---------- Runtime stage: only what the pipeline needs to run ----------
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# libpq5 is the PostgreSQL client library psycopg2 links against at runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# run as an unprivileged user, not root
RUN useradd --create-home --uid 1000 etl

WORKDIR /app
# the pipeline writes its log file into /app, so the user must own it
RUN chown etl:etl /app

# install the pre-built wheels; no compiler in this image
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index /wheels/* && rm -rf /wheels

COPY --chown=etl:etl . .

USER etl

CMD ["python", "main.py"]
