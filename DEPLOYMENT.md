# SentinelBank AI — Deployment Guide

Covers running the full stack (PostgreSQL, FastAPI backend, Next.js frontend) with Docker Compose, from a clean machine. This is a production-style prototype, not a production deployment — see **Security** below before putting it anywhere beyond your own machine.

## Prerequisites

- Docker Desktop (or Docker Engine + Compose v2) — `docker compose version` should print `v2.x` or later.
- Ports `5433` (Postgres), `8000` (backend), `3000` (frontend) free on the host, unless you override them.

## 1. Environment setup

```bash
cp .env.example .env
```

Edit `.env` and set real values:

| Variable | Used by | Notes |
|---|---|---|
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | `db` container | Picks the database name/credentials for a brand-new volume. Changing these after the volume already exists does **not** rename the existing database/role. |
| `DATABASE_URL` | Local (non-Docker) `uvicorn`/`alembic` only | Points at the host-mapped port `127.0.0.1:5433`. Inside Docker Compose, `backend`/`migrate` ignore this and connect via the service name `db:5432` instead — see `docker-compose.yml`'s `x-backend-env` anchor. |
| `JWT_SECRET_KEY` | backend | Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. Anyone with this value can mint a valid token for any user/role. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | backend | Token lifetime. |
| `NEXT_PUBLIC_API_BASE_URL` (optional) | frontend build | Only set this if the API is published somewhere other than `http://localhost:8000`. It's baked into the browser JS bundle at build time — see **Architecture note** below. |

`.env` is gitignored and must never be committed. `.env.example` holds placeholders only.

## 2. Start the stack

```bash
docker compose up --build -d
```

This builds the `backend` and `frontend` images, then starts services in dependency order:

1. `db` — starts, waits for `pg_isready`.
2. `migrate` — runs `alembic upgrade head` once `db` is healthy, then exits (`docker compose ps` will show it as `Exited (0)` — that's success, not a crash).
3. `backend` — starts once `migrate` completes successfully; its own healthcheck polls `/health/database`, so it isn't considered healthy until it can actually reach Postgres.
4. `frontend` — starts once `backend` is healthy.

Check progress:

```bash
docker compose ps
docker compose logs -f migrate   # should end with "Running upgrade ... -> af842f8e4605, baseline schema"
docker compose logs -f backend
```

Once `frontend` shows `healthy`, open `http://localhost:3000`.

## 3. Demo accounts

Seeded automatically by the backend on startup (`backend/db_seed.py`), idempotently:

| Email | Password | Role |
|---|---|---|
| `admin@sentinelbank.ai` | `Admin123!` | ADMIN |
| `analyst@sentinelbank.ai` | `Analyst123!` | ANALYST |

**Development-only credentials.** Never reuse these, or any value from `.env.example`, anywhere reachable by anyone else.

## 4. Backups and restore

```bash
scripts/backup-db.sh
```

Takes a `pg_dump` custom-format snapshot of the running `db` container into `backups/<timestamp>.dump` (gitignored). Safe to run against a live database — it doesn't block writers or modify anything.

To restore:

```bash
scripts/restore-db.sh backups/sentinelbank_20260101T000000Z.dump
```

This loads the dump into a **new** database (`restore_scratch` by default) on the same Postgres container — it never overwrites the live database in place. Inspect the restored data first:

```bash
docker exec -it sentinelbank-postgres psql -U <user> -d restore_scratch
```

Only promote it to the live database (destructive — stop `backend`/`migrate` first) if you're actually recovering from data loss; the script prints the exact `ALTER DATABASE ... RENAME TO ...` commands for that at the end of its output.

This procedure was verified end-to-end before being documented here: a real backup was taken and restored into a scratch database, and its table/row counts were confirmed to match the source.

## 5. Stopping / cleaning up

```bash
docker compose down          # stop and remove containers, keep the data volume
docker compose down -v       # also delete the Postgres data volume
```

## Architecture notes

- **Browser vs. Docker-internal URLs.** The frontend does all its data fetching client-side, in the browser — so `NEXT_PUBLIC_API_BASE_URL` must be an address the browser can reach (e.g. `http://localhost:8000`), never a Compose service name like `http://backend:8000`. Next.js inlines `NEXT_PUBLIC_*` values into the JS bundle at `next build` time, which is why it's passed as a Docker build `ARG`, not a runtime environment variable.
- **DB connection string.** `backend/db.py` reads `DATABASE_URL` from the environment, falling back to the root `.env` file only if it isn't already set. Docker Compose sets it explicitly (via the `x-backend-env` anchor in `docker-compose.yml`) to use the service name `db` on its internal port `5432` — the same code works unmodified for local (host, port `5433`) and containerized (Compose network, port `5432`) runs.
- **Migrations run once, not on every boot.** The one-shot `migrate` service is the only thing that runs `alembic upgrade head`; `backend` never runs migrations itself, so scaling `backend` to multiple replicas can't race multiple migration attempts against each other.

## Security

- `JWT_SECRET_KEY` and database credentials are supplied only via `.env` / the Compose `environment:` block — never baked into an image layer or committed to source control. Check `docker history <image>` yourself if you want to confirm no secret ever appears in a layer.
- The demo accounts in **3** are explicitly development-only. Any deployment reachable by someone other than you must replace `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, and the demo account passwords with real, secret values before going live.
- This prototype has not been through a formal production security review (TLS termination, secrets management, network policy, rate limiting, etc. are all out of scope here) — treat it as a demonstration of the application and its deployment path, not a production deployment.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `migrate` container exits non-zero | Can't reach `db`, or a migration genuinely fails | `docker compose logs migrate`. Confirm `db` is healthy first (`docker compose ps`). |
| `backend` never becomes healthy | `/health/database` can't reach Postgres | Check `docker compose logs backend`; confirm `migrate` actually completed (`service_completed_successfully`), not just started. |
| Frontend loads but every API call fails / shows a network error in the browser console | `NEXT_PUBLIC_API_BASE_URL` was baked in as a Docker-internal address, or the backend isn't published on the host port the frontend was built against | Rebuild the frontend image with the correct `NEXT_PUBLIC_API_BASE_URL` build arg: `docker compose build --build-arg NEXT_PUBLIC_API_BASE_URL=http://localhost:8000 frontend`. Changing this requires a rebuild, not just a restart — it's compiled into the JS bundle. |
| `npm ci` fails during the frontend image build with "lock file is out of sync" | `frontend/package-lock.json` was regenerated on a different OS/platform and is missing Linux-specific optional dependency entries | Regenerate it from inside a Linux container: `docker run --rm -v "$(pwd)/frontend:/app" -w /app node:20-alpine npm install --package-lock-only`, then commit the result. |
| `docker compose up` reuses stale containers/images after a Dockerfile change | Compose only rebuilds images you tell it to | `docker compose up --build`, or `docker compose build --no-cache <service>` for a fully clean rebuild. |
| Port already in use (`5433`, `8000`, or `3000`) | A local dev server or another stack is already bound to that port | Stop the conflicting process, or override the host port in a `docker-compose.override.yml`. |
| Need to test a clean install without touching real data | The real stack is already running with real data in its volume | Use a separate Compose project name and override `container_name`/ports, e.g. `docker compose -p sentinelbank_test -f docker-compose.yml -f <override-file> up --build`. The project name alone does **not** avoid container-name or port collisions, since `container_name` and `ports` in `docker-compose.yml` are literal — an override file is required to change those too. |
