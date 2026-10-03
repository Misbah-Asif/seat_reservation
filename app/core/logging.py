"""Structured JSON logs to stdout, with a request id on every line.

Every request gets an id: the client's X-Request-ID if it looks safe, else a
new one. It's put on every log line written while handling that request and
returned in the X-Request-ID response header, so one id finds everything about
one request. Fields added during the request (user_id, outcome) ride along too.

Logs go to stdout, where the hosting platform collects them. Writing happens in
a background thread (QueueHandler/QueueListener), so a burst of log lines never
blocks request handling on console I/O.

Never logged: tokens, the admin key, request bodies.
"""

import atexit
import json
import logging
import queue
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import QueueHandler, QueueListener
from typing import Any

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

logger = logging.getLogger("app.request")

# Fields for the current request (request_id, user_id, outcome). A dict, so code
# anywhere in the request (auth, routes) can add to it and every later log line
# includes it.
_request_ctx: ContextVar[dict[str, Any] | None] = ContextVar("request_ctx", default=None)

# Client-supplied ids are only reused if they're short and plain: anything else
# could be used to forge or break log lines.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Routes hit constantly by the platform or a scraper: logged at DEBUG only.
_QUIET_ROUTES = {"/health/live", "/health/ready", "/metrics"}

# Attributes every LogRecord has; anything else on a record came from `extra=`.
# color_message is uvicorn's copy of its message with terminal colour codes.
_RECORD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {
    "message",
    "asctime",
    "color_message",
}


def log_context() -> dict[str, Any]:
    """The current request's log fields. Outside a request: a throwaway dict."""
    ctx = _request_ctx.get()
    return ctx if ctx is not None else {}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        out.update(_request_ctx.get() or {})
        out.update({k: v for k, v in vars(record).items() if k not in _RECORD_ATTRS})
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


_configured = False


def setup_logging(level: str) -> None:
    """Route all logging (ours and uvicorn's) to JSON on stdout. Idempotent."""
    global _configured
    if _configured:
        return
    _configured = True

    # Formatting happens in the calling thread (QueueHandler.prepare), so the
    # request context is still available; the listener thread only writes.
    log_queue: queue.SimpleQueue[logging.LogRecord] = queue.SimpleQueue()
    queue_handler = QueueHandler(log_queue)
    queue_handler.setFormatter(JsonFormatter())
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(logging.Formatter("%(message)s"))
    listener = QueueListener(log_queue, stdout_handler)
    listener.start()
    atexit.register(listener.stop)

    root = logging.getLogger()
    root.handlers[:] = [queue_handler]
    root.setLevel(level.upper())

    # uvicorn's own messages (startup, errors) also become JSON via the root.
    for name in ("uvicorn", "uvicorn.error"):
        uv = logging.getLogger(name)
        uv.handlers.clear()
        uv.propagate = True
    # Replaced by our access line below, which has the request id and route.
    logging.getLogger("uvicorn.access").disabled = True


class  RequestLoggingMiddleware:
    """Assigns the request id, writes one access line per request, and turns
    an unexpected exception into a logged, JSON 500 carrying the request id."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        request_id = incoming if _SAFE_REQUEST_ID.match(incoming) else uuid.uuid4().hex
        token = _request_ctx.set({"request_id": request_id})
        start = time.perf_counter()
        status: int | None = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append("X-Request-ID", request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception("unhandled error")
            if status is not None:  # response already started: can't replace it
                raise
            status = 500
            await send({
                "type": "http.response.start",
                "status": 500,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"x-request-id", request_id.encode()),
                ],
            })
            await send({
                "type": "http.response.body",
                "body": json.dumps({"error": "internal_error", "request_id": request_id}).encode(),
            })
        finally:
            route = scope.get("route")
            route_path = route.path if route is not None else None
            logger.log(
                logging.DEBUG if route_path in _QUIET_ROUTES else logging.INFO,
                "request",
                extra={
                    "method": scope["method"],
                    "route": route_path,
                    "path": scope["path"],
                    "status": status,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            _request_ctx.reset(token)
