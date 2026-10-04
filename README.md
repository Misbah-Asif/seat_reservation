# Seat Reservation

A service that sells assigned seats for a show, built to stay correct under an on-sale stampede: a seat is never sold twice, a user never exceeds the per-user limit, and a retried request never books twice. It's observable live through health checks, Prometheus metrics and structured logs.

FastAPI (async) · PostgreSQL · SQLAlchemy 2 + asyncpg · deployed on Railway.

- **Live URL:** https://seat-reservation.up.railway.app
- **API docs (Swagger):** https://seat-reservation.up.railway.app/docs
- **Metrics:** https://seat-reservation.up.railway.app/metrics
- **Live logs under load (screen recording):** `<link to recording>`
- **Design write-up:** [WRITEUP.md](WRITEUP.md)

## Quick start against the live service

```bash
export URL=https://seat-reservation.up.railway.app
export ADMIN=<admin key for the live deployment, shared with the submission>

# 1. create a show (admin)
curl -s -X POST $URL/shows -H "X-Admin-Key: $ADMIN" -H 'content-type: application/json' \
  -d '{"name":"friday-night","seats":["A1","A2","A3"],"price_paise":25000}'

# 2. get a user token
TOKEN=$(curl -s -X POST $URL/auth/token -H 'content-type: application/json' \
  -d '{"user_id":"alice"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

# 3. reserve (identity comes from the token, never the body)
curl -s -X POST $URL/shows/<show_id>/reserve -H "Authorization: Bearer $TOKEN" \
  -H 'content-type: application/json' -d '{"seats":["A1"],"idempotency_key":"k1"}'

# 4. show state and counts
curl -s $URL/shows/<show_id>
```

## API

| Method | Path | Auth | What it does |
|---|---|---|---|
| `POST` | `/shows` | Admin key | Create a show and all its seats (all `available`) |
| `GET` | `/shows/{show_id}` | none | Per-seat status and counts (`available + held + confirmed == total_seats`) |
| `POST` | `/shows/{show_id}/reserve` | User token | Reserve seats (all-or-nothing, idempotent) |
| `GET` | `/shows/{show_id}/reservations` | User token | The caller's **own** reservations for that show |
| `POST` | `/reservations/{reservation_id}/cancel` | User token | Cancel your own reservation; its seats become available again |
| `POST` | `/auth/token` | none | Token for a given `user_id` (demo login) |
| `POST` | `/auth/tokens` | none | Tokens for `count` random users, up to 10,000 per call (for load tests) |
| `GET` | `/health/live` | none | Liveness: the process is up |
| `GET` | `/health/ready` | none | Readiness: the database answers; **503** when it doesn't |
| `GET` | `/metrics` | none | Prometheus metrics |

### Reserve behaviour

- **All-or-nothing:** a request for `["A12","A13"]` books both, or neither. If any seat is taken, the answer is `409` and lists the taken seats; the free ones stay free.
- **Idempotency:** the same `idempotency_key` with the same body returns the original reservation (`200`). The same key with different seats returns `409 idempotency_key_reused`.
- **Per-user limit:** a user can hold at most `per_user_limit` seats per show (default 4, set per show or via `DEFAULT_PER_USER_LIMIT`).
- **Money:** integer paise, never floats.

| Status | `error` | Meaning |
|---|---|---|
| `201` | | Booked |
| `200` | | Idempotent replay: the original reservation |
| `409` | `seats_unavailable` | At least one seat is taken (`unavailable_seats` lists them) |
| `409` | `per_user_limit_exceeded` | The booking would exceed the limit |
| `409` | `idempotency_key_reused` | Same key, different request |
| `404` | `show_not_found` / `seats_not_found` / `reservation_not_found` | Not found (also returned when cancelling someone else's reservation) |
| `401` | | Missing, invalid or expired token / admin key |
| `422` | | Invalid request body (e.g. duplicate seats, float price) |

## Auth

- **Users:** HS256 JWT in `Authorization: Bearer <token>`. The token's `sub` is the user id. Tokens last 30 minutes (`TOKEN_TTL_SECONDS`).
- **Getting tokens:** `/auth/token` and `/auth/tokens` are a **demo issuer** for testing. There are no real accounts, so anyone can get a token for any user id. Verification is the real part: in production this would be replaced by a login service.
- **Admin:** `X-Admin-Key: <ADMIN_API_KEY>` on `POST /shows`.
- **Swagger:** click **Authorize** and paste the token (without `Bearer`) and/or the admin key.

## Run locally

### With Docker (recommended: same image as the deployment)

```bash
docker compose up --build        # or: podman compose up --build
```

- API on http://localhost:8000. Postgres runs in its own container, and `db/schema.sql` is loaded automatically on first start.
- No setup needed on a clean clone: local-only demo secrets are used. The admin key is `local-dev-admin-key-change-me`.
- The database is also reachable from your machine on `localhost:5433` (user / password `seat_app`, database `seat_reservation`).
- Reset everything: `docker compose down -v`.

### Without Docker

```bash
python3.12 -m venv env && source env/bin/activate
pip install -r requirements.txt
createdb seat_reservation
psql -d seat_reservation -f db/schema.sql
cp .env.example .env              # fill in DATABASE_URI, JWT_SECRET, ADMIN_API_KEY
uvicorn main:app --reload
```

### Configuration (env vars)

| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URI` | (required) | `postgresql+asyncpg://user:pass@host:5432/db` |
| `JWT_SECRET` | (required) | Signing secret for user tokens (≥ 16 chars) |
| `ADMIN_API_KEY` | (required) | Admin key for `POST /shows` (≥ 16 chars) |
| `TOKEN_TTL_SECONDS` | 1800 | User token lifetime |
| `DEFAULT_PER_USER_LIMIT` | 4 | Limit for new shows that don't set one |
| `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT` | 10 / 10 / 30 | Connection pool |
| `LOG_LEVEL` | INFO | `DEBUG` also logs `/health/*` and `/metrics` calls |
| `READY_TIMEOUT_SECONDS` | 2 | `/health/ready` gives up after this |

The app refuses to start if a required secret is missing.

## Burst test (one command)

```bash
ADMIN_API_KEY=<key> ./burst.sh <BASE_URL> [--requests 2000] [--concurrency 200] [--seats N]
```

It needs only `python3` (standard library). It reproduces the on-sale stampede in **one mixed burst**:
- a **hot-seat storm** (30% of requests on one seat);
- random bookings;
- parallel retries with the same key;
- one user firing 10 parallel requests against limit 4;
- a bulk request with one seat already taken;
- key reuse with different seats;
- overlapping multi-seat requests;
- a spoofed `user_id` in the body.

It prints the outcome distribution (confirmed / declined by reason / 5xx), latency and a failure report, then **PASS/FAIL checks** for the correctness bar:
- one winner per hot seat, and no seat sold twice;
- limits and idempotency hold;
- counts add up **during and after** the burst;
- `/metrics` matches the responses;
- zero 5xx.

Details: [docs/BURST_SCRIPT.md](docs/BURST_SCRIPT.md).

**Latest live run** (from a laptop in India against Railway US West):
```
./burst.sh https://seat-reservation.up.railway.app --requests 20000 --concurrency 500
20,066 reserves in 70.6s (284 req/s) · 0 x 5xx · 0 unanswered
hot seat H1: 1 winner, 5,999 x 409 · ALL 19 CHECKS PASSED · /metrics matched exactly
```

## Observability

- **Health:** `/health/live` never touches the database. `/health/ready` runs `SELECT 1` on its own connection (outside the request pool, so a busy pool doesn't make it report "not ready"), with a 2 s timeout, and returns 503 when the database is unreachable.
- **Metrics** (`/metrics`, Prometheus text format):
  - `reservations_confirmed_total`
  - `reservations_declined_total{reason}`: `seat_taken`, `per_user_limit`, `idempotent_replay`, `idempotency_key_reused`, `seats_not_found`, `show_not_found`
  - `reservations_cancelled_total`
  - `seats_available` / `seats_held` / `seats_confirmed{show_id}`: read from the database on every scrape, so they always match `GET /shows/{id}`
  - `http_requests_total{method,route,status}` and `http_request_duration_seconds`

  Counters live in the app's memory and reset on restart. The app runs as **one process** so the counters are exact.
- **Logs:** one JSON line per request on stdout, with `request_id`, `user_id`, `outcome`, `seats` (plus `unavailable_seats` / `held` when declined), `status` and `duration_ms`.
  - The request id comes from the client's `X-Request-ID` if it's safe, otherwise it's generated. It's returned on every response.
  - Unexpected errors are logged once with a traceback and returned as a JSON 500 that carries the request id.
  - Tokens, keys and request bodies are never logged.
  - **Log access:** Railway's log viewer is account-only, so live logs under load are shown in the [screen recording](<link to recording>).
  - **About the "rate limit" lines in Railway's logs:** during a burst you'll see lines like this, marked as errors:
    ```
    Railway rate limit reached for deployment, update your application to reduce the logging rate. Messages dropped: 21
    ```
    - **This is not an application error.** Railway writes this message itself: the Railway plan this service runs on accepts only a limited number of log lines per second. The app writes one line per request, so during a burst of thousands of requests per second, Railway skips some lines **in its log viewer**.
    - **Requests are not affected:** every request is still handled and answered. The burst runs show 0 × 5xx, and `/metrics` counts every request, including the ones whose log line was dropped.
    - **So exact counts come from `/metrics`** and the burst script's output; logs are for tracing individual requests by `request_id`.

## Deployment (Railway)

The app is built from the `Dockerfile`: one uvicorn worker, a non-root user, `PORT` from the platform. Postgres is Railway's managed database on the same private network.

1. **Add PostgreSQL** to the project.
2. **Run `db/schema.sql` once against it:** `psql "<DATABASE_PUBLIC_URL>" -f db/schema.sql`. Railway doesn't run `docker-compose.yml`, so tables aren't created automatically there.
3. **Set the app's variables:**
   - `DATABASE_URI=postgresql+asyncpg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}`
   - `JWT_SECRET`, `ADMIN_API_KEY`, and pool sizes.
4. **Health check path** `/health/ready`, **replicas = 1** (the metrics are per process).

Options considered: [docs/DEPLOYMENT_OPTIONS.md](docs/DEPLOYMENT_OPTIONS.md).

## Project layout

```
main.py                     app setup: routers, middleware, startup/shutdown
app/api/router/             auth, health, metrics, shows, reservation
app/services/               business logic (reserve, cancel, show state)
app/repositories/           database queries (locking lives here)
app/db/                     models, session, enums
app/core/                   config, auth, logging, metrics, errors
db/schema.sql               full schema (Postgres 13+), safe to re-run
burst.sh, scripts/burst.py  load test + correctness checks
docs/                       assignment, schema plan, deployment options, burst guide, decision log
```
