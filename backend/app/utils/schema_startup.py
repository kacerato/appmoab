import asyncio
import logging
from collections.abc import Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.utils.schema_bootstrap import ensure_runtime_schema

SCHEMA_BOOTSTRAP_LOCK_ID = 89889020260616
STARTUP_DATA_LOCK_ID = 89889020260617
TRANSIENT_SCHEMA_ERRORS = (
    "deadlock detected",
    "deadlockdetectederror",
    "locknotavailableerror",
    "could not obtain lock",
)


def _is_transient_schema_error(exc: Exception) -> bool:
    message = f"{type(exc).__name__} {exc}".lower()
    return any(fragment in message for fragment in TRANSIENT_SCHEMA_ERRORS)


async def run_schema_bootstrap(
    engine: AsyncEngine,
    create_all: Callable,
    logger: logging.Logger,
    *,
    attempts: int = 5,
) -> None:
    """Serializa e executa o bootstrap de schema para deploys com multiplos workers."""
    for attempt in range(1, attempts + 1):
        try:
            async with engine.begin() as conn:
                await conn.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": SCHEMA_BOOTSTRAP_LOCK_ID})
                await conn.run_sync(create_all)
                await ensure_runtime_schema(conn)
            if attempt > 1:
                logger.info("Bootstrap de schema concluido apos %s tentativa(s).", attempt)
            return
        except Exception as exc:
            if attempt >= attempts or not _is_transient_schema_error(exc):
                raise
            wait_seconds = min(0.5 * attempt, 3.0)
            logger.warning(
                "Bootstrap de schema encontrou lock/deadlock transitório na tentativa %s/%s; nova tentativa em %.1fs: %s",
                attempt,
                attempts,
                wait_seconds,
                exc,
            )
            await asyncio.sleep(wait_seconds)
