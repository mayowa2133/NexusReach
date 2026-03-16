from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import get_or_create_user
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me")
async def get_me(
    user: Annotated[User, Depends(get_or_create_user)],
):
    """Return the current authenticated user. Creates user record on first call."""
    return {
        "id": str(user.id),
        "email": user.email,
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
