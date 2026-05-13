from datetime import datetime

from pydantic import BaseModel


class SubscriptionResponse(BaseModel):
    plan: str
    is_paid: bool
    stripe_status: str | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False


class CheckoutSessionResponse(BaseModel):
    checkout_url: str


class PortalSessionResponse(BaseModel):
    portal_url: str
