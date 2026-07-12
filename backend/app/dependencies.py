import asyncio
import uuid
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth_tokens
from app.config import settings
from app.database import get_db
from app.observability import capture_event, identify_user
from app.models.user import User
from app.models.profile import Profile
from app.models.settings import UserSettings

security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: uuid.UUID
    email: str | None = None


def _fallback_email(user_id: uuid.UUID) -> str:
    return f"{user_id}@users.nexusreach.invalid"


async def get_current_auth_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
) -> AuthenticatedUser:
    """Validate Supabase JWT and return the current user context."""
    if settings.auth_mode == "dev":
        if not settings.dev_auth_bypass_enabled:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=(
                    "Dev auth bypass requires "
                    "NEXUSREACH_DEV_AUTH_BYPASS_ENABLED=true."
                ),
            )
        email = settings.dev_user_email.strip().lower() if settings.dev_user_email.strip() else None
        return AuthenticatedUser(user_id=settings.dev_user_id, email=email)

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )

    token = credentials.credentials
    try:
        payload = await asyncio.to_thread(auth_tokens.decode_supabase_token, token)
        sub = payload.get("sub")
        if sub is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing sub",
            )
        email = payload.get("email")
        normalized_email = email.strip().lower() if isinstance(email, str) and email.strip() else None
        return AuthenticatedUser(user_id=uuid.UUID(sub), email=normalized_email)
    except jwt.PyJWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )
    except ValueError as e:
        # sub is present but not a valid UUID — reject as a bad token, not a 500.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {e}",
        )


async def get_or_create_user(
    auth_user: Annotated[AuthenticatedUser, Depends(get_current_auth_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Get the user record, creating it on first login."""
    user_id = auth_user.user_id
    desired_email = auth_user.email or _fallback_email(user_id)

    # Serialize first-login bootstrap for this identity. Browsers issue several
    # authenticated requests immediately after sign-in; without this
    # transaction-scoped lock they can all observe a missing row and race the
    # primary/unique keys. PostgreSQL releases the lock on commit or rollback.
    lock_key = int.from_bytes(user_id.bytes[:8], byteorder="big", signed=True)
    await db.execute(text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})

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

        identify_user(str(user_id), {"email": desired_email})
        capture_event(str(user_id), "user_signed_up")
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


async def get_current_user_id(
    user: Annotated[User, Depends(get_or_create_user)],
) -> uuid.UUID:
    """Compatibility dependency that returns the current bootstrapped user ID."""
    return user.id
