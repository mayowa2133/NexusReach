import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.user import User
from app.models.profile import Profile
from app.models.settings import UserSettings

security = HTTPBearer()


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: uuid.UUID
    email: str | None = None


def _fallback_email(user_id: uuid.UUID) -> str:
    return f"{user_id}@users.nexusreach.invalid"


async def get_current_auth_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> AuthenticatedUser:
    """Validate Supabase JWT and return the current user context."""
    token = credentials.credentials
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
        sub = payload.get("sub")
        if sub is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing sub",
            )
        email = payload.get("email")
        normalized_email = email.strip().lower() if isinstance(email, str) and email.strip() else None
        return AuthenticatedUser(user_id=uuid.UUID(sub), email=normalized_email)
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )


async def get_current_user_id(
    auth_user: Annotated[AuthenticatedUser, Depends(get_current_auth_user)],
) -> uuid.UUID:
    """Compatibility dependency that returns just the current user ID."""
    return auth_user.user_id


async def get_or_create_user(
    auth_user: Annotated[AuthenticatedUser, Depends(get_current_auth_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Get the user record, creating it on first login."""
    user_id = auth_user.user_id
    desired_email = auth_user.email or _fallback_email(user_id)

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    changed = False

    if user is None:
        user = User(id=user_id, email=desired_email)
        db.add(user)
        changed = True

        # Create default profile and settings
        db.add(Profile(user_id=user_id))
        db.add(UserSettings(user_id=user_id))
        changed = True
    else:
        placeholder_email = _fallback_email(user_id)
        if (not user.email or user.email == placeholder_email) and auth_user.email:
            user.email = auth_user.email
            changed = True

        profile_result = await db.execute(select(Profile).where(Profile.user_id == user_id))
        if profile_result.scalar_one_or_none() is None:
            db.add(Profile(user_id=user_id))
            changed = True

        settings_result = await db.execute(select(UserSettings).where(UserSettings.user_id == user_id))
        if settings_result.scalar_one_or_none() is None:
            db.add(UserSettings(user_id=user_id))
            changed = True

    if changed:
        await db.commit()
        await db.refresh(user)

    return user
