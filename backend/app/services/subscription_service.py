import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import stripe_client
from app.models.subscription import Subscription

logger = logging.getLogger(__name__)


async def get_subscription(db: AsyncSession, user_id: uuid.UUID) -> Subscription:
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return sub


async def is_paid(db: AsyncSession, user_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(Subscription).where(Subscription.user_id == user_id)
    )
    sub = result.scalar_one_or_none()
    return sub is not None and sub.is_paid


async def get_or_create_stripe_customer(
    db: AsyncSession, user_id: uuid.UUID, email: str
) -> str:
    sub = await get_subscription(db, user_id)
    if sub.stripe_customer_id:
        return sub.stripe_customer_id

    customer = stripe_client.create_customer(email=email, user_id=str(user_id))
    sub.stripe_customer_id = customer.id
    await db.commit()
    return customer.id


async def handle_checkout_completed(db: AsyncSession, session_obj: dict) -> None:
    customer_id = session_obj.get("customer")
    subscription_id = session_obj.get("subscription")
    if not customer_id:
        logger.warning("checkout.session.completed without customer_id")
        return

    result = await db.execute(
        select(Subscription).where(Subscription.stripe_customer_id == customer_id)
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        logger.warning("No subscription row for stripe customer %s", customer_id)
        return

    sub.plan = "pro"
    sub.stripe_subscription_id = subscription_id
    sub.stripe_status = "active"
    await db.commit()
    logger.info("Activated pro plan for user %s", sub.user_id)


async def handle_subscription_updated(db: AsyncSession, stripe_sub: dict) -> None:
    sub_id = stripe_sub.get("id")
    customer_id = stripe_sub.get("customer")

    result = await db.execute(
        select(Subscription).where(
            (Subscription.stripe_subscription_id == sub_id)
            | (Subscription.stripe_customer_id == customer_id)
        )
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        logger.warning("subscription.updated for unknown subscription %s", sub_id)
        return

    sub.stripe_status = stripe_sub.get("status")
    sub.cancel_at_period_end = stripe_sub.get("cancel_at_period_end", False)

    period = stripe_sub.get("current_period_start")
    if period:
        sub.current_period_start = datetime.fromtimestamp(period, tz=timezone.utc)
    period_end = stripe_sub.get("current_period_end")
    if period_end:
        sub.current_period_end = datetime.fromtimestamp(period_end, tz=timezone.utc)

    if sub.stripe_status in ("active", "trialing"):
        sub.plan = "pro"
    elif sub.stripe_status in ("canceled", "unpaid"):
        sub.plan = "free"

    await db.commit()
    logger.info("Updated subscription for user %s: status=%s", sub.user_id, sub.stripe_status)


async def handle_subscription_deleted(db: AsyncSession, stripe_sub: dict) -> None:
    sub_id = stripe_sub.get("id")
    customer_id = stripe_sub.get("customer")

    result = await db.execute(
        select(Subscription).where(
            (Subscription.stripe_subscription_id == sub_id)
            | (Subscription.stripe_customer_id == customer_id)
        )
    )
    sub = result.scalar_one_or_none()
    if sub is None:
        logger.warning("subscription.deleted for unknown subscription %s", sub_id)
        return

    sub.plan = "free"
    sub.stripe_status = "canceled"
    sub.cancel_at_period_end = False
    sub.current_period_start = None
    sub.current_period_end = None
    await db.commit()
    logger.info("Canceled subscription for user %s", sub.user_id)
