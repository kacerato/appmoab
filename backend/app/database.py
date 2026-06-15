"""
AquaMoab — Conexão assíncrona com Neon PostgreSQL via SQLAlchemy.

Usa asyncpg como driver e managed sessions com context manager.
"""

import ssl
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()


def _normalize_neon_url(url: str) -> str:
    """
    Normaliza a URL do Neon para funcionar com asyncpg.
    Remove parâmetros SSL da query string (serão passados via connect_args).
    """
    # Garante driver asyncpg
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Remove TODOS os parâmetros SSL da URL para evitar channel_binding
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    # Remove ssl, sslmode, channel_binding e variantes
    for key in list(params.keys()):
        if key.lower() in ("ssl", "sslmode", "channel_binding", "sslrootcert", "sslcert", "sslkey"):
            del params[key]
    clean_query = urlencode(params, doseq=True)
    clean_url = urlunparse(parsed._replace(query=clean_query))
    return clean_url


db_url = _normalize_neon_url(settings.database_url)

# SSL context para Neon (exige TLS) — passado APENAS via connect_args
ssl_context = ssl.create_default_context()
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

engine = create_async_engine(
    db_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=settings.database_pool_size,
    max_overflow=settings.database_max_overflow,
    pool_timeout=settings.database_pool_timeout_seconds,
    connect_args={"ssl": ssl_context},
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base declarativa para todos os modelos SQLAlchemy."""
    pass


async def get_db() -> AsyncSession:
    """
    Dependency injection para FastAPI.
    Gera uma session por request e fecha automaticamente.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
