"""Request/task-local identity for paid provider reservation boundaries."""

import contextvars
import hashlib
import uuid
from collections.abc import Awaitable
from typing import TypeVar

_subject: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "paid_work_subject", default=None
)
_operation_scope: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "paid_work_operation_scope", default=None
)
_T = TypeVar("_T")


def set_subject(user_id: uuid.UUID) -> None:
    _subject.set(user_id)


def get_subject() -> uuid.UUID | None:
    return _subject.get()


def operation_id(service: str, fingerprint: str = "") -> str:
    """Return a stable call ID inside a redelivered Celery task."""
    scope = _operation_scope.get()
    if scope is None:
        return f"paid:{uuid.uuid4()}"
    digest = hashlib.sha256(
        f"{scope}\0{service}\0{fingerprint}".encode("utf-8")
    ).hexdigest()
    return f"paid:{digest}"


async def run_in_operation_scope(
    awaitable: Awaitable[_T], scope: str | None
) -> _T:
    """Isolate one worker delivery and reset identity after it completes."""
    subject_token = _subject.set(None)
    scope_token = _operation_scope.set(scope)
    try:
        return await awaitable
    finally:
        _operation_scope.reset(scope_token)
        _subject.reset(subject_token)
