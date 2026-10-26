# Production image for the FastAPI backend.
#
# Migrations are deliberately NOT run here -- see docker-compose.yml's
# one-shot `migrate` service, which runs `alembic upgrade head` and must
# complete successfully before this container's dependents start. Baking
# "run migrations on boot" into the app container makes multi-replica
# startups race each other against the same database.
# Pinned to the exact patch version this app is developed and tested
# against locally (`python --version`), not just the 3.13 minor line --
# see requirements.txt for the matching pinned dependency versions.
FROM python:3.13.1-slim

WORKDIR /app

# Build tools are needed to compile psycopg's optional extras on some
# platforms; removed from the final layer to keep the image lean.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 appuser \
    && chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# /health has no dependencies (DB, auth) -- it only proves the process is
# alive and serving. Readiness w.r.t. the database is a separate concern,
# checked by docker-compose's own healthcheck against /health/database.
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD curl -f http://127.0.0.1:8000/health || exit 1

# Workers configurable via UVICORN_WORKERS so the same image scales without
# a rebuild; defaults to a conservative single worker for this prototype.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port 8000 --workers ${UVICORN_WORKERS:-1}"]
