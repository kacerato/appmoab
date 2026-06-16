"""Aplicacao principal FastAPI do AquaMoab."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import Base, async_session_factory, engine
from app.routers import (
    auth,
    customers,
    dashboard,
    deductions,
    hydrometers,
    invoices,
    readings,
    system_settings,
    tariffs,
    webhooks,
    whatsapp_messages,
)
from app.services.billing import seed_default_tariffs
from app.services.hydrometer_codes import ensure_numeric_hydrometer_codes
from app.services.efi_api import efi_service
from app.services.whatsapp_api import whatsapp_service
from app.utils.middleware import performance_and_security_middleware
from app.utils.schema_bootstrap import ensure_runtime_schema

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("%s v%s iniciando...", settings.app_name, settings.app_version)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await ensure_runtime_schema(conn)

    async with async_session_factory() as session:
        try:
            await seed_default_tariffs(session)
            updated_hydrometers = await ensure_numeric_hydrometer_codes(session)
            if updated_hydrometers:
                logger.info("Hidrometros migrados para codigo numerico: %s", updated_hydrometers)
            await session.commit()
        except Exception as exc:
            logger.warning("Seed de startup falhou: %s", exc)

    logger.info("WhatsApp: %s", "ATIVADO" if settings.whatsapp_enabled else "DESATIVADO")
    logger.info("Efí API: %s", "HOMOLOGACAO" if settings.efi_sandbox else "PRODUCAO")

    yield

    await efi_service.close()
    await whatsapp_service.close()
    logger.info("AquaMoab encerrado.")


app = FastAPI(
    title=settings.app_name,
    description="Sistema de gestao de distribuicao de agua - Poco Artesiano Moab",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.middleware("http")(performance_and_security_middleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

os.makedirs(settings.upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

app.include_router(auth.router, prefix="/api")
app.include_router(customers.router, prefix="/api")
app.include_router(hydrometers.router, prefix="/api")
app.include_router(readings.router, prefix="/api")
app.include_router(invoices.router, prefix="/api")
app.include_router(tariffs.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(deductions.router, prefix="/api")
app.include_router(webhooks.router, prefix="/api")
app.include_router(whatsapp_messages.router, prefix="/api")
app.include_router(system_settings.router, prefix="/api")


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "revision": os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("VERCEL_GIT_COMMIT_SHA") or "",
        "whatsapp_enabled": settings.whatsapp_enabled,
        "payment_provider": "efi",
        "efi_sandbox": settings.efi_sandbox,
        "cors_origins": settings.cors_origin_list,
    }
