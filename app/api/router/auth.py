import uuid

from fastapi import APIRouter

from app.core.auth import create_user_token
from app.schemas.auth import CreateTokenRequest, CreateTokensRequest, UserToken

# Demo token issuer for testing and load bursts. There are no real accounts:
# anyone can get a token for any user id. Verification (app/core/auth.py) is
# the real part; in production this router would be replaced by a login
# service and nothing else would change.
router = APIRouter(prefix="/auth", tags=["auth"])


# Plain `def`, not `async def`: signing is CPU work, so FastAPI runs these in a
# worker thread instead of blocking the event loop for other requests.
@router.post("/token", response_model=UserToken)
def create_token(payload: CreateTokenRequest) -> UserToken:
    return UserToken(user_id=payload.user_id, token=create_user_token(payload.user_id))


@router.post("/tokens", response_model=list[UserToken])
def create_tokens(payload: CreateTokensRequest) -> list[UserToken]:
    # Random ids, so separate calls never hand out the same user twice.
    user_ids = (f"u-{uuid.uuid4().hex}" for _ in range(payload.count))
    return [UserToken(user_id=uid, token=create_user_token(uid)) for uid in user_ids]
