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
| `JWT_SECRET_KEY` | backend | Generate with `python -c "import secrets; print(secrets.token_hex(32))"`. Anyone with this value can mint a valid token for any user/role. The backend refuses to start if this is missing *or* still the literal placeholder text from `.env.example`. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | backend | Token lifetime. |
| `NEXT_PUBLIC_API_BASE_URL` (optional) | frontend build | Only set this if the API is published somewhere other than `http://localhost:8000`. It's baked into the browser JS bundle at build time — see **Architecture note** below. |
| `OLLAMA_HOST` (optional) | backend | Only needed inside Docker Compose. Defaults to `http://host.docker.internal:11434` — Ollama itself isn't containerized here, so this points at the host. Override if Ollama runs somewhere else. |

`docker compose` itself refuses to start (with a clear error naming the missing variable) if `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `JWT_SECRET_KEY` aren't set — these are required (`${VAR:?...}`) in `docker-compose.yml`, not just defaulted to blank.

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

### Recovery downtime and limitations

This procedure was run twice end-to-end (not just read as a plan): a real backup was taken of the live dev database and restored into a scratch database, with its table/row counts (users, alerts, transactions) confirmed to match the source both times. Measured on the demo dataset's current size (2 users, 7 alerts, 21 transactions):

- `backup-db.sh`: ~1 second.
- `restore-db.sh` (into the scratch database): ~1.5 seconds.

These scale with data volume, not with application traffic — `pg_dump` doesn't block writers, so taking a backup never causes downtime by itself.

**Actual recovery (promoting a restored backup over the live database) does require downtime**, since it's done by renaming databases, not a live cutover:

1. Stop `backend` and `migrate` (or `docker compose stop backend`) so nothing is writing to, or reconnecting against, the database being renamed.
2. Restore into a scratch database (`restore-db.sh`), inspect it.
3. Rename the live database out of the way, then rename the scratch database into its place (commands printed by `restore-db.sh`).
4. Restart `backend`.

Total downtime is the restore time above plus however long `backend` takes to pass its own readiness check on restart — observed at roughly 10-20 seconds for this stack (dominated by the healthcheck's `start_period`/`interval`, not actual startup work). For a dataset many times larger than the current demo data, expect the restore step itself to dominate; it hasn't been measured at a larger scale.

**Known limitations, not yet addressed:**
- No automated/scheduled backups (no cron, no offsite/cloud storage) — `backup-db.sh` is a manual, on-demand operation only.
- Recovery has only been exercised restoring onto the *same* running Postgres container. Restoring onto a freshly provisioned Postgres instance uses the same standard `pg_restore` mechanism but hasn't been explicitly tested in this environment.
- The promotion step (step 3 above) is a short but real outage window; there's no zero-downtime/blue-green story here.

## 5. Stopping / cleaning up

```bash
docker compose down          # stop and remove containers, keep the data volume
docker compose down -v       # also delete the Postgres data volume
```

## Architecture notes

- **Browser vs. Docker-internal URLs.** The frontend does all its data fetching client-side, in the browser — so `NEXT_PUBLIC_API_BASE_URL` must be an address the browser can reach (e.g. `http://localhost:8000`), never a Compose service name like `http://backend:8000`. Next.js inlines `NEXT_PUBLIC_*` values into the JS bundle at `next build` time, which is why it's passed as a Docker build `ARG`, not a runtime environment variable.
- **DB connection string.** `backend/db.py` reads `DATABASE_URL` from the environment, falling back to the root `.env` file only if it isn't already set. Docker Compose sets it explicitly (via the `x-backend-env` anchor in `docker-compose.yml`) to use the service name `db` on its internal port `5432` — the same code works unmodified for local (host, port `5433`) and containerized (Compose network, port `5432`) runs.
- **Migrations run once, not on every boot.** The one-shot `migrate` service is the only thing that runs `alembic upgrade head`; `backend` never runs migrations itself, so scaling `backend` to multiple replicas can't race multiple migration attempts against each other.
- **Liveness vs. readiness.** `backend/Dockerfile`'s own `HEALTHCHECK` hits `/health` (process liveness only, no dependencies) — correct for a standalone `docker run` with no Compose context. `docker-compose.yml` overrides this for the `backend` service to hit `/health/database` instead (real readiness, including the DB), since that's what `frontend`'s `depends_on: condition: service_healthy` actually needs. Verified directly: with the database reachable at boot, `/health` and `/health/database` both return 200; if the database is stopped *after* a successful boot, `/health` keeps returning 200 (the process is still alive) while `/health/database` correctly returns 503. If the database is unreachable *at boot*, the process fails to start at all (see **Known limitations** below) — neither endpoint is reachable in that case, which is a different failure mode from either health check "failing."
- **Ollama runs on the host, not in Compose.** `backend`'s default `OLLAMA_HOST` (`investigation/llm_client.py`) is `127.0.0.1:11434`, which inside a container means the container itself, not the host machine. `docker-compose.yml` overrides this to `http://host.docker.internal:11434` for the `backend` service (with an `extra_hosts` entry so this also resolves on native Linux Docker Engine, not just Docker Desktop). Verified end-to-end: a real investigation was run through the containerized backend against a host-installed Ollama server and produced a grounded, persisted report.

## Security

- `JWT_SECRET_KEY` and database credentials are supplied only via `.env` / the Compose `environment:` block — never baked into an image layer or committed to source control. Verified directly: the built backend image was scanned and contains no `.env*` file, and `docker compose config` with an empty env file is refused outright (see below) rather than silently defaulting.
- Secrets are mandatory, not just documented as such: `docker compose up` refuses to start (clear error, names the missing variable) if `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, or `JWT_SECRET_KEY` are unset. The backend additionally refuses to start if `JWT_SECRET_KEY` is still the literal placeholder text from `.env.example` — the one value anyone can read directly from the public repo, so a half-configured checkout can't accidentally go live with a secret that isn't actually secret.
- The demo accounts in **3** are explicitly development-only. Any deployment reachable by someone other than you must replace `JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, and the demo account passwords with real, secret values before going live. There is currently no separate flag to disable automatic demo-account seeding — it runs on every backend startup, idempotently, regardless of environment. Treat "has anyone rotated the demo passwords and JWT secret" as the actual control, not "is seeding disabled."
- The frontend bundle was scanned directly (both the built `.next/static` output and the `.next/standalone` server bundle) for every secret-shaped string this app uses (`JWT_SECRET_KEY`, `POSTGRES_PASSWORD`, `DATABASE_URL`, the example placeholder text) — zero matches. The only `process.env` reference anywhere in `frontend/src` is `NEXT_PUBLIC_API_BASE_URL`, which is intentionally public (it's a URL the browser already has to know to make API calls).
- This prototype has not been through a formal production security review (TLS termination, network policy, rate limiting, secrets-manager integration, etc. are all out of scope here) — treat it as a demonstration of the application and its deployment path, not a production deployment. See `RELEASE.md` for the full threat model and known limitations.

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
| Investigation requests fail / time out, but `/health/database` is fine | Ollama isn't reachable from inside the container | Confirm Ollama is actually running on the host (`curl http://127.0.0.1:11434/api/tags` from the host, not inside a container). On native Linux Docker Engine, confirm `host.docker.internal` resolves inside the container (`docker compose exec backend getent hosts host.docker.internal`) — the `extra_hosts` entry in `docker-compose.yml` should handle this, but very old Docker Engine versions may not support `host-gateway`. |
| `docker compose up` fails immediately with "required variable ... is missing a value" | `.env` wasn't created, or is missing one of the required secrets | `cp .env.example .env` and fill in real values (step 1) — this is deliberate, not a bug: see **Security**. |
