# Updated table + DB plan (price on seat, seat_type enum, one-table reservation)

## Context
- You want the price on each **seat**, because `regular` / `special` / `vip` seats will have different prices.
- `seat_type` must be an enum with exactly those three values.
- The current `reservation` table stores one row per seat. Combined with `UNIQUE(user_id, idempotency_key)`, that blocks multi-seat bookings.
- We discussed one-table vs two-table designs. This plan uses the **one-table design**: `reservation` (one row per booking, with a `seat_labels` snapshot) plus `seat.reservation_id` (the current owner).
- "Is A15 reserved, and by whom?" is answered from the `seat` table. The array is only used for idempotent replays.

**Scope of this step: the schema for all three tables, plus updating `POST /shows`.** The `/reserve` logic (locking, per-user limit, expiry) is the next step and will be discussed first.

All tables keep `AuditMixin` (`is_active, created_at, updated_at, deleted_at`). The enums are stored as `varchar` + CHECK (`native_enum=False`), which is the same pattern as the current `seat.status`.

## Tables

### `show`
| column | type | rule |
|---|---|---|
| id | int PK | |
| name | varchar(100) | NOT NULL |
| per_user_limit | int | NOT NULL, default 4, CHECK ≥ 1 |

`price_paise` is **removed**; the price now lives on the seat.

### `seat`
| column | type | rule |
|---|---|---|
| id | int PK | |
| show_id | FK → show.id | NOT NULL |
| seat_label | varchar(100) | NOT NULL, the label, e.g. "A15" |
| seat_type | enum `regular` / `special` / `vip` | NOT NULL, default `regular` |
| price_paise | int | NOT NULL, CHECK ≥ 0 |
| status | enum `available` / `held` / `confirmed` | NOT NULL, default `available` |
| reservation_id | uuid FK → reservation.id | NULL when the seat is available |

Constraints:
- `UNIQUE(show_id, seat_label)`: one A15 per show. It's also the index used for "is A15 reserved?".
- `INDEX(show_id, status)`: makes the available/held/confirmed counts fast.
- `CHECK ((status = 'available') = (reservation_id IS NULL))`: the database itself rejects a held seat with no owner, or an available seat that still points to a reservation.

### `reservation` (replaces the current table)
| column | type | rule / why |
|---|---|---|
| id | uuid PK, default `gen_random_uuid()` | the `reservation_id` returned by the API. A UUID so ids can't be guessed and don't reveal sales volume. `show` and `seat` keep int ids because they're public or never exposed |
| show_id | FK → show.id | NOT NULL |
| user_id | varchar(100) | NOT NULL, the token's subject (was int) |
| idempotency_key | varchar(100) | NOT NULL |
| seat_labels | varchar(100)[] | NOT NULL, a snapshot of the requested seats, **always sorted**. Used to replay the original response. Same key with a different show_id or seat_labels → 409 (`request_hash` was dropped: comparing these columns does the same job) |
| amount_paise | int | NOT NULL, CHECK ≥ 0, the sum of seat prices at booking time |
| status | enum `held` / `confirmed` / `cancelled` | NOT NULL |

Constraints:
- `UNIQUE(user_id, idempotency_key)`: exactly-once is enforced by the database.
- `INDEX(show_id, user_id)`: used for the per-user limit check.

### Enums (`app/db/models/enums.py`)
- `SeatTypeEnum`: **new**, with `regular`, `special` and `vip`.
- `SeatStatusEnum`: unchanged (`available`, `held`, `confirmed`).
- `ReservationStatusEnum`: `pending`/`failed` → **`held`, `confirmed`, `cancelled`**. Declined requests are never saved, so a `failed` status isn't needed.

## `POST /shows` request (still compatible with the brief)
- A string seat like `"A1"` → `regular` at the top-level `price_paise`. This is the brief's exact format.
- An object seat `{"seat_id":"V1","seat_type":"vip","price_paise":60000}` → typed seat. If it has no `price_paise`, it uses the top-level price.
- Top-level `price_paise` is the default price and isn't stored on `show`.
- Labels must be unique across both forms. Prices are StrictInt ≥ 0.
- The response includes `seat_type` and `price_paise` for each seat.

## Files to change
- `app/db/models/enums.py`: as described above.
- `app/db/models/show.py`: drop `price_paise` and its CHECK.
- `app/db/models/seat.py`: `seat_type` enum, `price_paise`, `reservation_id` FK, and the status/reservation CHECK.
- `app/db/models/reservation.py`: rewrite to match the table above. Remove the per-seat `seat_id` column.
- `app/schemas/shows.py`: add `SeatIn`, make `seats: list[str | SeatIn]`, extend `SeatOut`.
- `app/repositories/show_repository.py`: `create_with_seats` takes `(label, type, price)` dicts.
- `app/services/show_service.py`: resolve each seat's type and price with the default fallback.
- `docs/SCHEMA_PLAN.md`: save a copy of this plan in the repo.
- Schema changes: **done manually by the user with SQL in psql**. Alembic was removed until the user has learned it. The tables are created fresh, so nothing needs backfilling.
- `per_user_limit`: NOT NULL with no `DEFAULT`, plus `CHECK (per_user_limit >= 1)`. The default comes from the app setting `DEFAULT_PER_USER_LIMIT` (4), not the database.

## Decided in the next step (not now)
- Release model: explicit cancel, or a hold that expires. If it expires, `reservation.expires_at` gets added then.
- How the per-user limit stays race-free (which row gets locked).
- Multi-seat behaviour: all-or-nothing or best-effort, and the lock order.

## Verification
- After running the SQL, `\d show`, `\d seat`, `\d reservation` in psql to confirm the columns and constraints.
- In psql, check the CHECK constraint: `UPDATE seat SET status='held' WHERE id=1` (with no reservation_id) → must fail.
- Run uvicorn, then curl:
  - The brief's format → 201, every seat `regular` at that price.
  - The mixed format with a vip seat at 60000, and a special seat with no price that falls back to the default.
  - `seat_type: "gold"` → 422. A float price → 422. A duplicate label across both forms → 422.
