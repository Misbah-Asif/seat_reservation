import secrets
import time
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import settings
from app.core.logging import log_context

JWT_ALGORITHM = "HS256"

# Declared as OpenAPI security schemes (not plain header parameters) so Swagger
# UI shows an "Authorize" button and sends them; it ignores a header parameter
# named Authorization. auto_error=False: we raise our own 401s below.
_user_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="UserToken",
    description="User JWT from POST /auth/token or POST /auth/tokens.",
)
_admin_key_header = APIKeyHeader(
    name="X-Admin-Key",
    auto_error=False,
    scheme_name="AdminKey",
    description="Admin key (ADMIN_API_KEY) for creating shows.",
)


def create_user_token(user_id: str) -> str:
    """Signed token whose `sub` is the user id. Nothing else is in it."""
    now = int(time.time())
    payload = {"sub": user_id, "iat": now, "exp": now + settings.token_ttl_seconds}
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user_id(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_user_bearer)],
) -> str:
    """The only source of identity: the verified token's `sub`, never the body."""
    # None when the header is missing or isn't "Bearer <token>".
    if credentials is None or not credentials.credentials.strip():
        raise _unauthorized("missing bearer token")
    try:
        # algorithms is pinned: a token claiming "none" or another alg is rejected.
        payload = jwt.decode(
            credentials.credentials.strip(),
            settings.jwt_secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("token expired")
    except jwt.InvalidTokenError:
        raise _unauthorized("invalid token")
    log_context()["user_id"] = payload["sub"]
    return payload["sub"]


async def require_admin(
    x_admin_key: Annotated[str | None, Depends(_admin_key_header)],
) -> None:
    # compare_digest: constant-time, so the key can't be guessed from timing.
    if x_admin_key is None or not secrets.compare_digest(
        x_admin_key.encode(), settings.admin_api_key.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing or invalid admin key"
        )
