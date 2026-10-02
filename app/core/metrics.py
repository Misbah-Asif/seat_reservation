"""Prometheus metrics.

Counters live in this process's memory and reset on restart (normal for
Prometheus). They're only correct per process, so run ONE app process per
instance (the app is async, so one process already handles the concurrency).

Seat gauges are not kept in memory: they're read from the database on every
scrape, so they always match GET /shows/{id}, even right after a restart.
"""

import time

from prometheus_client import Counter, Gauge, Histogram, disable_created_metrics
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Skip the extra *_created timestamp series the client adds to every counter;
# they're noise for this service.
disable_created_metrics()

# --- Reservations: counted where the API decides the outcome -----------------

RESERVATIONS_CONFIRMED = Counter(
    "reservations_confirmed",  # exposed as reservations_confirmed_total
    "Reserve requests that booked seats (HTTP 201)",
)
RESERVATIONS_DECLINED = Counter(
    "reservations_declined",
    "Reserve requests that booked nothing, by reason",
    ["reason"],
)
RESERVATIONS_CANCELLED = Counter(
    "reservations_cancelled",
    "Reservations cancelled (a repeat cancel of the same reservation is not counted)",
)

IDEMPOTENT_REPLAY = "idempotent_replay"
DECLINE_REASONS = (
    "seat_taken",
    "per_user_limit",
    IDEMPOTENT_REPLAY,
    "idempotency_key_reused",
    "seats_not_found",
    "show_not_found",
)
# Create every label up front so each reason shows as 0 before its first
# event: a before/after comparison then works from the very first scrape.
for _reason in DECLINE_REASONS:
    RESERVATIONS_DECLINED.labels(reason=_reason)

# --- Seats: refreshed from the database on each scrape -----------------------

SEATS_AVAILABLE = Gauge("seats_available", "Seats currently available", ["show_id"])
SEATS_HELD = Gauge("seats_held", "Seats currently held", ["show_id"])
SEATS_CONFIRMED = Gauge("seats_confirmed", "Seats currently confirmed", ["show_id"])

# --- HTTP: every request, to spot any 5xx and watch latency under load -------

HTTP_REQUESTS = Counter(
    "http_requests", "HTTP requests by route and status", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Request latency by route",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)


class HttpMetricsMiddleware:
    """Counts every request and its latency.

    Labelled by route *template* (/shows/{show_id}/reserve), not the real path,
    so ids don't create a new time series per request. A request whose handler
    crashes is counted as 500.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            route = scope.get("route")
            route_label = route.path if route is not None else "unmatched"
            method = scope["method"]
            HTTP_REQUESTS.labels(method=method, route=route_label, status=str(status)).inc()
            HTTP_LATENCY.labels(method=method, route=route_label).observe(
                time.perf_counter() - start
            )
