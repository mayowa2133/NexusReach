from sqlalchemy.pool import NullPool

import app.database as database
from app.database import _engine_kwargs


def test_engine_kwargs_use_bounded_pool_defaults():
    kwargs = _engine_kwargs()

    assert kwargs["echo"] is False
    assert kwargs["pool_size"] == 3
    assert kwargs["max_overflow"] == 0
    assert kwargs["pool_timeout"] == 30
    assert kwargs["pool_recycle"] == 1800
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_use_lifo"] is True


def test_use_null_pool_engine_rebinds_sessionmaker():
    """Worker children must swap to NullPool and rebind the shared sessionmaker.

    Guards the fork/pooler-safety fix for the asyncpg MissingGreenlet /
    ConnectionDoesNotExist errors seen on app.tasks.* in Sentry.
    """
    original = database.engine
    try:
        assert not isinstance(database.engine.pool, NullPool)

        database.use_null_pool_engine()

        assert isinstance(database.engine.pool, NullPool)
        # Task modules import the `async_session` object directly, so the same
        # sessionmaker must now be bound to the NullPool engine in place.
        assert database.async_session.kw["bind"] is database.engine
        assert isinstance(database.async_session.kw["bind"].pool, NullPool)
    finally:
        database.engine = original
        database.async_session.configure(bind=original)
