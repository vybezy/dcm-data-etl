# build stage: compile dependencies that need a C compiler
FROM python:3.11-slim-bookworm AS builder

# gcc, the C library headers (libc6-dev) and the PostgreSQL headers are
# needed to compile psycopg2; none of them end up in the runtime image
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


# runtime stage: only what the pipeline needs to run
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# libpq5 is PostgreSQL client library psycopg2 links against at runtime
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 \
    && rm -rf /var/lib/apt/lists/*

# run as an unprivileged user, not root
RUN useradd --create-home --uid 1000 etl

WORKDIR /app

RUN chown etl:etl /app

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index /wheels/* && rm -rf /wheels

COPY --chown=etl:etl . .

USER etl

CMD ["python", "main.py"]
