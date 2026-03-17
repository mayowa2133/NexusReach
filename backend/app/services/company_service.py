"""Company service — query and manage company records."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company


async def get_companies(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    starred: bool | None = None,
) -> list[Company]:
    """List companies for a user, optionally filtered by starred."""
    stmt = select(Company).where(Company.user_id == user_id)
    if starred is not None:
        stmt = stmt.where(Company.starred == starred)
    stmt = stmt.order_by(Company.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_company(
    db: AsyncSession,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
) -> Company | None:
    """Get a single company scoped to user."""
    stmt = select(Company).where(
        Company.id == company_id,
        Company.user_id == user_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def toggle_company_starred(
    db: AsyncSession,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    starred: bool,
) -> Company:
    """Toggle a company's starred status."""
    company = await get_company(db, user_id, company_id)
    if not company:
        raise ValueError("Company not found")
    company.starred = starred
    await db.commit()
    await db.refresh(company)
    return company
