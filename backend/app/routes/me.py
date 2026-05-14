from fastapi import APIRouter, Depends

from ..auth.jwt_tokens import current_user
from ..config import settings
from ..db import User

router = APIRouter(tags=["me"])


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict:
    return {
        "id": user.id,
        "speckle_user_id": user.speckle_user_id,
        "name": user.name,
        "email": user.email,
        "avatar": user.avatar,
        # Viewer needs a Speckle token. For M1 we hand the user's token to the
        # SPA; M2 should mint short-lived tokens instead.
        "speckle_token": user.speckle_access_token,
        "speckle_public_url": settings.speckle_public_url,
    }
