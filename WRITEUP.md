# Write-up

## 1. The atomic decision

**Mechanism: row locks taken in a fixed order, then the check, then the write, all in one Postgres transaction.** There is no read-then-write gap: a seat is only checked **while it is locked**.

`POST /shows/{id}/reserve` runs one transaction (`app/services/reservation_service.py`, queries in `app/repositories/reservation_repository.py`):

1. **Per-user lock:** `SELECT pg_advisory_xact_lock(hashtextextended(user_id, 0))`. One user's requests run one at a time; different users never wait for each other. This is what makes steps 2 and 4 race-free.
2. **Idempotency lookup** (section 2).
3. **Unlocked pre-check:** if any requested seat is already not `available`, decline with 409 immediately. This is only an optimisation: during a hot-seat storm, the losers leave without queueing on the row lock. It never decides a win.
4. **Per-user limit:** the seats this user holds for the show (non-cancelled reservations) + requested ≤ `per_user_limit`.
5. **The decision:**
   ```sql
   SELECT … FROM seat
   WHERE show_id = $1 AND seat_label = ANY($2)
   ORDER BY seat_label
   FOR UPDATE;
   ```
   Then, while holding the locks: every requested seat must exist and be `available`, otherwise roll back and return 409 with the taken seats.
6. **Write:** insert the reservation, then `UPDATE seat SET status='confirmed', reservation_id=… WHERE id IN (locked ids)`, then commit. The amount is summed from the locked rows' prices.

**Why it's race-free:**
- **`FOR UPDATE` makes concurrent requests for the same seat wait.** When the first commits, the next one gets the lock and sees the **committed** status (`confirmed`), so it declines.
- **There's no window where two requests both see `available`.** That gives exactly one winner per seat.
- **Every decline rolls back immediately,** so locks are held only as long as needed.

**Database-level backstops:** even buggy application code couldn't double-sell, because of:
- `UNIQUE (show_id, seat_label)`, and
- `CHECK ((status = 'available') = (reservation_id IS NULL))`: a seat has an owner exactly when it isn't available.

**Multi-seat requests and deadlock:**
- **Fixed lock order:** every request takes its locks in the same order (the user lock first, then seats sorted by `seat_label`). Two requests can never each hold a seat the other is waiting for. `[A1,A2]` vs `[A2,A1]` both lock `A1` first; one simply waits.
- **Cancel uses the same order** (user, reservation row, seats by label).
- **All-or-nothing:** if any seat is taken, the whole transaction rolls back and nothing is booked; the 409 lists the taken seats.
- **Tested** with 30 overlapping multi-seat requests in opposite orders inside the 20k burst: no deadlocks, no 5xx.

## 2. Idempotency

- **Where the key is stored:** on the reservation row, `reservation.idempotency_key`, with `UNIQUE (user_id, idempotency_key)`. Keys are scoped **per user**, because the user comes from the token. The row also stores the **sorted** `seat_labels` and `show_id` of the original request.
- **How exactly-once is enforced:**
  1. The lookup by `(user_id, key)` runs **under the per-user advisory lock**, so two concurrent copies of the same request are serialized. The second one finds the first one's reservation instead of booking again.
  2. The unique constraint is a backstop: a second row with the same key can't exist.
  3. The lookup comes **before** any availability or limit check. Otherwise the retry of a winning request would get "seat taken" (its own seat) or "over limit" (its own seats).
- **Replay response:** the original reservation with **200** (not 201). A retry must never look like a second winner, e.g. in "exactly one 201 per hot seat".
- **Same key, different body:** if `show_id` or the sorted seats differ from the stored ones, the answer is `409 idempotency_key_reused`, and nothing is booked. (I dropped a separate `request_hash` column: comparing the stored fields does the same job.)
- **Declined requests aren't stored,** so retrying a declined request is evaluated again. That's correct, since a seat may have been freed in the meantime. "Exactly once" applies to **bookings**.
- **After a cancel,** a late retry of the original key returns the cancelled reservation. It does not book again.

**Verified:**
- Locally: 50 parallel copies of one request gave 1 × 201 and 49 × 200, with one reservation id.
- Live burst: 5 parallel copies gave 1 × 201 and 4 × 200.
- Live burst: requests resent after dropped connections came back as 200 replays, not double bookings.

## 3. Holds and expiry

**Chosen model: explicit cancel, no time-boxed holds.** A successful reserve is immediately `confirmed`, matching the brief's success response.

`POST /reservations/{id}/cancel`:
- **Owner only:** the user comes from the token. Someone else's reservation returns **404, the same answer as a missing one**, so a stranger can't tell that a booking exists.
- **Lock order** is the same as reserve: user, reservation row (`FOR UPDATE`), then its seats in label order.
- **Seats are freed with `UPDATE seat … WHERE reservation_id = <this reservation>`,** never by label. A seat that now belongs to someone else can't match, so a **release can never free a seat confirmed to another user**. Tested: after a cancel, B books the freed seat; A cancelling the old reservation again leaves it with B.
- **The seats go back to `available`** and are immediately re-bookable. The user's limit is freed too.
- **Cancelling an already-cancelled reservation returns 200 and changes nothing**, so retried cancels are safe.

**Why not holds:** there's no payment step in this service, so a hold would only add a timer that can expire under the user. The schema already has `held`. With a payment step, I'd reserve as `held` with `expires_at`, confirm on payment, and release expired holds with a guarded update: `UPDATE seat … WHERE status='held' AND reservation_id=… AND expires_at < now()`.

## 4. Consistency vs availability under a partition

**This is a CP design: when the app can't reach the database, it refuses to sell rather than risk selling a seat twice.**

- **Postgres (one primary) is the single source of truth.** Every booking decision is made inside it, under row locks. Nothing is decided from a cache or a replica.
- **If the app is cut off from the database:**
  - bookings fail;
  - `/health/ready` returns **503**, so the platform stops routing new traffic to that instance;
  - `/health/live` stays OK, so the platform doesn't restart a healthy process for a database problem.
- **No seat can be sold twice in that state.** The cost is availability: nobody can buy until the database is reachable again.
- **Why that trade-off:** selling one seat to two people means refunds, angry customers and lost trust. A few minutes of "try again" during an outage is recoverable. Correctness wins over availability for the system of record.
- **Honest gap:** a request already in progress when the database disappears currently ends as a **500** (a clean JSON 500 with the request id), not a 503. Mapping database-unreachable and pool-timeout errors to `503 Retry-After` is on the "next" list.

## 5. Observability: what I'd get paged for at 2am

**What's there:**
- **`/health/live` and `/health/ready`.** Readiness runs on its own connection, so a busy pool during a burst doesn't make it report "not ready".
- **Prometheus `/metrics`:**
  - reservations confirmed, declined by reason, cancelled;
  - seats available / held / confirmed per show, read from the database on every scrape;
  - HTTP requests by route and status, plus a latency histogram.
- **JSON logs:** one line per request, carrying `request_id`, user, outcome, seats and duration. The id is returned in `X-Request-ID`, so any failure can be traced.

**Page someone (wake up) for:**
1. **Any sustained 5xx:** `rate(http_requests_total{status=~"5.."}[5m]) > 0`. Declines are 4xx by design, so a 5xx is always a bug or an outage.
2. **Readiness failing:** the database is unreachable, so nobody can buy.
3. **The invariant broken:** `available + held + confirmed != total_seats` for any show, or a seat with two owners. This should be impossible, so if it happens, stop sales.
4. **Crash loop / restarts** during an on-sale (it also resets the counters).
5. **Reserve p99 latency** above the clients' timeout (say > 5 s for 5 minutes): requests are queuing and buyers will start seeing timeouts.

**Don't page for:**
- **A spike in `409 seat_taken`:** that's what an on-sale looks like.
- **`per_user_limit` declines.**

These go on a dashboard (confirmed rate, declines by reason, seats left per show), not into an alert.

**Load-test evidence (live, Railway US West, run from a laptop in India):**
- **The run:** `./burst.sh … --requests 20000 --concurrency 500`, i.e. 20,066 reserves in 70.6 s (284 req/s), 0 × 5xx, 0 unanswered.
- **Correctness:** hot seat with 1 winner and 5,999 × 409. All 19 checks passed: counts added up during and after, and `/metrics` matched the responses exactly.
- **Server-side latency** (from the histogram): median about 1 s, 92% under 2.5 s.
- **CPU:** `process_cpu_seconds_total` shows about **3.3 ms of CPU per request**. So one worker process tops out near 300 req/s, which is the limit we hit (see section 7).
- **Log caveat:** during a burst, Railway's logs show *"Railway rate limit reached for deployment, update your application to reduce the logging rate. Messages dropped: N"*, marked as an error. **It is not an application error:** it comes from the log rate limit of the Railway plan this runs on (one log line per request exceeds it at thousands of requests per second), so Railway skips some lines in its viewer. Requests are unaffected: 0 × 5xx, and `/metrics` counts every request. **`/metrics` is the exact count; logs are for tracing.** A fix would be shipping logs to a log service, or sampling `seat_taken` lines (section 7).

## 6. AI usage: directed vs decided

I used an AI coding assistant (Claude Code) throughout. **I set the requirements, made the data-model and API decisions, and ran the deployment and live testing.** It explained its proposals before I accepted them, and I changed several of them. It helped me in coding.

**I decided** (directed it, or chose between options it laid out):
- **Data model:**
  - the initial table structure;
  - **price per seat** (not per show) and seat types `regular`/`special`/`vip`;
  - **one reservation table**;
  - **dropping `request_hash`**;
  - **UUID reservation ids** (I raised the guessable-id concern);
  - `IDENTITY` over `SERIAL`;
- **Stack:** async everywhere (asyncpg); default per-user limit from an env var.
- **Reserve and cancel:**
  - reserve should be **"correct and scalable" from the start**, not simple first;
  - cancel rules: owner-only, seats freed, repeat cancel → 200;
  - a list-my-reservations endpoint that depends on the user id in the token.
- **The concurrency core:**
  - `SELECT … FOR UPDATE ORDER BY seat_label` with all-or-nothing;
  - idempotency before every decline, and 200 for replays.
- **Auth:** a **bulk token endpoint** for load testing, a single-token endpoint, a UUID admin key, 30-minute token expiry.
- **Observability & logs:**
  - in-memory counters plus seat gauges from the database, with a single worker;
  - JSON logging with request ids and minimum required request details for tracing.
- **Burst:**
  - seat details on the existing log line rather than log sampling;
  - most burst scenarios, one mixed burst, and the `--seats` option.
- **Deploy and scope:** Railway (Hobby, US West) with a manual schema step; cutting optional work on the last day.

**AI proposed, and I accepted after it explained:**
- **Concurrency:**
  - the per-user advisory lock;
  - the unlocked pre-check;
- **API and auth:** domain errors as 4xx with reason codes; JWT details (algorithm pinned, Swagger security schemes).
- **Observability:**
  - readiness on a separate connection;
- **Docker:** the Dockerfile and compose details.
- **Burst script internals:** keep-alive connections, resend-aware checks, the failure report.

**What I caught or pushed back on:**
- The Swagger auth header not being sent.
- The burst script calling the auth API once per scenario user: I had it fetch every user from one bulk `/auth/tokens` call, so the test traffic is almost entirely the reservation API.
- False failures in the first live burst. They turned out to be dropped connections plus resends, and the script now accounts for them.

## 7. What I'd do next

1. **Throughput:** run several workers (e.g. 4) with `prometheus_client`'s multiprocess mode. One Python process uses one CPU core, which capped us near 300 req/s (≈3.3 ms of CPU per request). Then trim CPU per request (fewer ORM round trips on the hot path).
2. **Return 503 + `Retry-After` instead of 500** when the database is unreachable or the pool times out.
3. **Holds with expiry and a payment step,** as described in section 3.
4. **Real authentication:** a login service or identity provider, RS256 keys, and turning the demo token endpoints off in production.
5. **Migrations (Alembic)** instead of a manual `schema.sql` step, and **automated tests in CI**: the burst scenarios as pytest, plus unit tests for the service.
6. **Log shipping:** send logs to a log service, with sampling for `seat_taken` lines, so a 20k burst isn't cut by the platform's log rate limit.
7. **Operational:** per-user / per-IP rate limiting; alert rules for section 5; a reconciliation job that checks the seat invariant continuously.
