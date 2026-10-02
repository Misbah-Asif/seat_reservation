import secrets
import time
from typing import Annotated

import jwt
from fastapi import Header, HTTPException, status

from app.core.config import settings

JWT_ALGORITHM = "HS256"


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
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    """The only source of identity: the verified token's `sub`, never the body."""
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized("missing bearer token")
    try:
        # algorithms is pinned: a token claiming "none" or another alg is rejected.
        payload = jwt.decode(
            token.strip(),
            settings.jwt_secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp"]},
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("token expired")
    except jwt.InvalidTokenError:
        raise _unauthorized("invalid token")
    return payload["sub"]


async def require_admin(
    x_admin_key: Annotated[str | None, Header()] = None,
) -> None:
    # compare_digest: constant-time, so the key can't be guessed from timing.
    if x_admin_key is None or not secrets.compare_digest(
        x_admin_key.encode(), settings.admin_api_key.encode()
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing or invalid admin key"
        )
