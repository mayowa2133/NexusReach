import logging
import uuid
from typing import Annotated

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients import stripe_client
from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user_id, get_or_create_user
from app.models.user import User
from app.schemas.subscription import (
    CheckoutSessionResponse,
    PortalSessionResponse,
    SubscriptionResponse,
)
from app.services import subscription_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subscription", tags=["subscription"])


@router.get("", response_model=SubscriptionResponse)
async def get_subscription(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    sub = await subscription_service.get_subscription(db, user_id)
    return SubscriptionResponse(
        plan=sub.plan,
        is_paid=sub.is_paid,
        stripe_status=sub.stripe_status,
        current_period_end=sub.current_period_end,
        cancel_at_period_end=sub.cancel_at_period_end,
    )


@router.post("/checkout", response_model=CheckoutSessionResponse)
async def create_checkout(
    user: Annotated[User, Depends(get_or_create_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    if not settings.stripe_secret_key:
        raise HTTPException(status_code=503, detail="Billing is not configured")

    customer_id = await subscription_service.get_or_create_stripe_customer(
        db, user.id, user.email
    )
    session = stripe_client.create_checkout_session(
        customer_id=customer_id,
        price_id=settings.stripe_price_id,
        success_url=f"{settings.frontend_url}/settings?subscription=success",
        cancel_url=f"{settings.frontend_url}/upgrade?canceled=true",
    )
    return CheckoutSessionResponse(checkout_url=session.url)


@router.post("/portal", response_model=PortalSessionResponse)
async def create_portal(
    user_id: Annotated[uuid.UUID, Depends(get_current_user_id)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    sub = await subscription_service.get_subscription(db, user_id)
    if not sub.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No billing account found")

    return_url = f"{settings.frontend_url}/settings"
    session = stripe_client.create_portal_session(
        customer_id=sub.stripe_customer_id, return_url=return_url
    )
    return PortalSessionResponse(portal_url=session.url)


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe_client.construct_webhook_event(payload, sig_header)
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event_type = event.get("type", "")
    data_obj = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        await subscription_service.handle_checkout_completed(db, data_obj)
    elif event_type == "customer.subscription.updated":
        await subscription_service.handle_subscription_updated(db, data_obj)
    elif event_type == "customer.subscription.deleted":
        await subscription_service.handle_subscription_deleted(db, data_obj)
    else:
        logger.debug("Unhandled Stripe event: %s", event_type)

    return {"received": True}
