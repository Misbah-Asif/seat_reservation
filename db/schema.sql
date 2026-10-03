-- Seat reservation schema (PostgreSQL 13+, for gen_random_uuid()).
--
-- Apply to an empty database:
--   psql "$DATABASE_URL" -f db/schema.sql
-- Safe to re-run: every object is created only if missing. It does not alter
-- tables that already exist.
--
-- Run it as the database owner (the same user the app connects as), so the app
-- owns the tables.

BEGIN;

CREATE TABLE IF NOT EXISTS show (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    -- No DEFAULT: the app fills it from DEFAULT_PER_USER_LIMIT when a request
    -- omits it, and stores the value so later setting changes don't affect it.
    per_user_limit  INTEGER NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    CONSTRAINT ck_show_per_user_limit_positive CHECK (per_user_limit >= 1)
);

-- One row per booking request, however many seats it covers.
CREATE TABLE IF NOT EXISTS reservation (
    -- UUID: reservation ids are exposed and must not be guessable.
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    show_id          INTEGER NOT NULL REFERENCES show (id),
    -- The auth token's subject, never taken from the request body.
    user_id          VARCHAR(100) NOT NULL,
    idempotency_key  VARCHAR(100) NOT NULL,
    -- Snapshot of the booked seats, always sorted. Used to replay the original
    -- response and to detect a key reused with a different request.
    seat_labels      VARCHAR(100)[] NOT NULL,
    -- Integer paise, summed from seat prices at booking time.
    amount_paise     INTEGER NOT NULL,
    status           VARCHAR(9) NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at       TIMESTAMPTZ,
    -- Exactly-once: a user's key can only ever create one reservation.
    CONSTRAINT uq_user_idemp UNIQUE (user_id, idempotency_key),
    CONSTRAINT ck_reservation_amount_non_negative CHECK (amount_paise >= 0),
    CONSTRAINT reservation_status CHECK (status IN ('held', 'confirmed', 'cancelled'))
);
-- Per-user limit: sum of a user's seats for a show.
CREATE INDEX IF NOT EXISTS ix_reservation_show_user ON reservation (show_id, user_id);

CREATE TABLE IF NOT EXISTS seat (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    show_id         INTEGER NOT NULL REFERENCES show (id),
    -- Human-facing label, e.g. 'A12'.
    seat_label      VARCHAR(100) NOT NULL,
    seat_type       VARCHAR(7) NOT NULL DEFAULT 'regular',
    price_paise     INTEGER NOT NULL,
    -- The column reservations race on: rows are locked (SELECT ... FOR UPDATE,
    -- in seat_label order) and checked under the lock before being taken.
    status          VARCHAR(9) NOT NULL DEFAULT 'available',
    -- Current owner; NULL while available.
    reservation_id  UUID REFERENCES reservation (id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at      TIMESTAMPTZ,
    -- One 'A12' per show. Also the index for looking a seat up by label.
    CONSTRAINT uq_show_seat UNIQUE (show_id, seat_label),
    CONSTRAINT seat_type CHECK (seat_type IN ('regular', 'special', 'vip')),
    CONSTRAINT seat_status CHECK (status IN ('available', 'held', 'confirmed')),
    CONSTRAINT ck_seat_price_non_negative CHECK (price_paise >= 0),
    -- A seat has an owner exactly when it isn't available. The database itself
    -- rejects a held seat with no owner, or a free seat still linked to one.
    CONSTRAINT ck_seat_owner_matches_status CHECK ((status = 'available') = (reservation_id IS NULL))
);
-- Seat counts by status (GET /shows/{id}, /metrics).
CREATE INDEX IF NOT EXISTS ix_seat_show_status ON seat (show_id, status);

COMMIT;
