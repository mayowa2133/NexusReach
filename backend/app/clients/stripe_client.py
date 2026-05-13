import stripe

from app.config import settings


def _client() -> stripe.StripeClient:
    return stripe.StripeClient(settings.stripe_secret_key)


def create_customer(email: str, user_id: str) -> stripe.Customer:
    return _client().customers.create(
        params={"email": email, "metadata": {"nexusreach_user_id": user_id}}
    )


def create_checkout_session(
    customer_id: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
) -> stripe.checkout.Session:
    return _client().checkout.sessions.create(
        params={
            "customer": customer_id,
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
    )


def create_portal_session(
    customer_id: str, return_url: str
) -> stripe.billing_portal.Session:
    return _client().billing_portal.sessions.create(
        params={"customer": customer_id, "return_url": return_url}
    )


def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.stripe_webhook_secret
    )
