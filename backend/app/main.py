"""
AquaMoab — Aplicação principal FastAPI.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import async_session_factory
from app.services.billing import seed_default_tariffs
from app.services.inter_api import inter_service
from app.services.whatsapp_api import whatsapp_service

# Routers
from app.routers import auth, customers, hydrometers, readings, invoices, tariffs, dashboard, deductions, webhooks

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(name)-30s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup e shutdown do app."""
    logger.info(f"🚀 {settings.app_name} v{settings.app_version} iniciando...")

    # Seed das tarifas padrão
    async with async_session_factory() as session:
        try:
            await seed_default_tariffs(session)
        except Exception as e:
            logger.warning(f"Seed de tarifas falhou (OK se tabela não existe ainda): {e}")

    logger.info(f"📊 WhatsApp: {'ATIVADO' if settings.whatsapp_enabled else 'DESATIVADO (flag off)'}")
    logger.info(f"🏦 Inter API: {'SANDBOX' if settings.inter_sandbox else 'PRODUÇÃO'}")

    yield

    # Shutdown
    await inter_service.close()
    await whatsapp_service.close()
    logger.info("👋 AquaMoab encerrado.")


app = FastAPI(
    title=settings.app_name,
    description="Sistema de Gestão de Distribuição de Água — Poço Artesiano Moab",
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static files (uploads)
import os
os.makedirs(settings.upload_dir, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=settings.upload_dir), name="uploads")

# Routers
app.include_router(auth.router, prefix="/api")
app.include_router(customers.router, prefix="/api")
app.include_router(hydrometers.router, prefix="/api")
app.include_router(readings.router, prefix="/api")
app.include_router(invoices.router, prefix="/api")
app.include_router(tariffs.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")
app.include_router(deductions.router, prefix="/api")
app.include_router(webhooks.router, prefix="/api")


@app.get("/api/health")
async def health_check():
    """Endpoint de saúde para monitoring."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "revision": os.getenv("RAILWAY_GIT_COMMIT_SHA") or os.getenv("VERCEL_GIT_COMMIT_SHA") or "",
        "whatsapp_enabled": settings.whatsapp_enabled,
        "inter_sandbox": settings.inter_sandbox,
    }
