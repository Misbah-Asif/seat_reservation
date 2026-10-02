from typing import Annotated

from fastapi import Header, HTTPException, status


# TODO: STUB. Replace with real token verification (e.g. a signed JWT whose `sub`
# is the user id). Today the bearer token *is* the user id, so anyone can claim
# any user. The point of the stub is the shape: identity comes only from the
# Authorization header via this one dependency, never from the request body,
# so swapping in real verification later touches only this function.
async def get_current_user_id(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip() or len(token) > 100:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()
