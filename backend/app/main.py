"""Aplicacao principal FastAPI do AquaMoab."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from sqlalchemy import text

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
)
from app.services.billing import seed_default_tariffs
from app.services.hydrometer_codes import ensure_numeric_hydrometer_codes
from app.services.inter_api import inter_service
from app.services.whatsapp_api import whatsapp_service

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
        await conn.execute(text("ALTER TABLE hydrometers ADD COLUMN IF NOT EXISTS red_digits INTEGER NOT NULL DEFAULT 3"))
        await conn.execute(text("ALTER TABLE hydrometers ADD COLUMN IF NOT EXISTS black_digits INTEGER"))
        await conn.execute(text("ALTER TABLE hydrometers ADD COLUMN IF NOT EXISTS qr_code_token VARCHAR(120)"))
        await conn.execute(text("UPDATE hydrometers SET qr_code_token = 'AQMOAB-' || replace(id::text, '-', '') WHERE qr_code_token IS NULL OR qr_code_token = ''"))
        await conn.execute(text("ALTER TABLE hydrometers ALTER COLUMN qr_code_token SET NOT NULL"))
        await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_hydrometers_qr_code_token ON hydrometers (qr_code_token)"))
        await conn.execute(text("ALTER TABLE hydrometers ADD COLUMN IF NOT EXISTS disconnected_at TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE hydrometers ADD COLUMN IF NOT EXISTS reconnected_at TIMESTAMP WITH TIME ZONE"))
        await conn.execute(text("ALTER TABLE hydrometers ADD COLUMN IF NOT EXISTS disconnection_reason TEXT"))
        await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS original_amount DOUBLE PRECISION"))
        await conn.execute(text("UPDATE invoices SET original_amount = amount WHERE original_amount IS NULL"))
        await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS custom_adjustment_amount DOUBLE PRECISION NOT NULL DEFAULT 0"))
        await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS late_fee_amount DOUBLE PRECISION NOT NULL DEFAULT 0"))
        await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS interest_amount DOUBLE PRECISION NOT NULL DEFAULT 0"))
        await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS days_overdue_charged INTEGER NOT NULL DEFAULT 0"))
        await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS adjustment_reason TEXT"))
        await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS charge_type VARCHAR(30) NOT NULL DEFAULT 'water'"))
        await conn.execute(text("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS daily_interest_percent DOUBLE PRECISION NOT NULL DEFAULT 0.033"))
        await conn.execute(text("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS late_fee_percent DOUBLE PRECISION NOT NULL DEFAULT 10"))
        await conn.execute(text("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS installation_fee_amount DOUBLE PRECISION NOT NULL DEFAULT 100"))
        await conn.execute(text("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS reconnection_fee_amount DOUBLE PRECISION NOT NULL DEFAULT 160"))
        await conn.execute(text("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS cut_notice_days_after_due INTEGER NOT NULL DEFAULT 5"))
        await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS red_digits INTEGER"))
        await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS black_digits INTEGER"))
        await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS hydrometer_brand VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS hydrometer_model VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS reasoning_log TEXT"))
        await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS divergence_reason TEXT"))

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
    logger.info("Inter API: %s", "SANDBOX" if settings.inter_sandbox else "PRODUCAO")

    yield

    await inter_service.close()
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
app.include_router(system_settings.router, prefix="/api")


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "revision": os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("VERCEL_GIT_COMMIT_SHA") or "",
        "whatsapp_enabled": settings.whatsapp_enabled,
        "inter_sandbox": settings.inter_sandbox,
        "cors_origins": settings.cors_origin_list,
    }
