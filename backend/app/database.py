import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings

logger = logging.getLogger(__name__)


def _engine_kwargs() -> dict:
    return {
        "echo": False,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_max_overflow,
        "pool_timeout": settings.db_pool_timeout_seconds,
        "pool_recycle": settings.db_pool_recycle_seconds,
        "pool_pre_ping": True,
        "pool_use_lifo": True,
    }


engine = create_async_engine(settings.database_url, **_engine_kwargs())
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def use_null_pool_engine() -> None:
    """Rebuild the global engine with ``NullPool`` for Celery worker children.

    Celery's prefork model forks worker children from a parent that has already
    imported this module, so every child inherits the same *pooled* ``engine``.
    Two failure modes follow, both seen in Sentry on ``app.tasks.*``:

    * Inherited asyncpg connections are bound to the parent's event loop. When a
      child pre-pings one outside that loop SQLAlchemy raises ``MissingGreenlet``.
    * The Supabase pooler reaps a connection while the child sits idle between
      the 5-15 min beat runs, so the next checkout hits
      ``ConnectionDoesNotExistError: connection was closed in the middle of
      operation`` / "connection reset by peer".

    ``NullPool`` opens a fresh connection per checkout and closes it on return,
    so nothing is shared across a fork or reused after the pooler drops it. Wired
    from ``worker_process_init`` (once per child); the FastAPI web service keeps
    its pooled engine and never calls this.
    """
    global engine
    inherited = engine
    # Drop the inherited pool's references without closing sockets that may be
    # shared with sibling processes; the NullPool engine owns all future ones.
    inherited.sync_engine.dispose(close=False)
    engine = create_async_engine(settings.database_url, echo=False, poolclass=NullPool)
    async_session.configure(bind=engine)
    logger.info("Worker DB engine reconfigured with NullPool (fork/pooler-safe)")


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:  # type: ignore[misc]
    async with async_session() as session:
        yield session
