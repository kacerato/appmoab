"""
AquaMoab — Script de seed para dados iniciais.

Cria o admin padrão e insere as tarifas se necessário.
Executar: python -m app.seed
"""

import asyncio
import logging

from app.database import async_session_factory, engine, Base
from app.models import *  # noqa: F401, F403
from app.models.user import User
from app.services.billing import seed_default_tariffs
from app.utils.security import hash_password

from sqlalchemy import select

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADMIN_EMAIL = "admin@aquamoab.com"
ADMIN_PASSWORD = "admin123"  # Mudar em produção!


async def main():
    # Cria todas as tabelas
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Tabelas criadas/verificadas")

    async with async_session_factory() as db:
        # Admin padrão
        result = await db.execute(select(User).where(User.email == ADMIN_EMAIL))
        if not result.scalar_one_or_none():
            admin = User(
                name="Administrador",
                email=ADMIN_EMAIL,
                password_hash=hash_password(ADMIN_PASSWORD),
                role="admin",
            )
            db.add(admin)
            logger.info(f"✅ Admin criado: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
        else:
            logger.info("ℹ️  Admin já existe")

        # Tarifas padrão
        await seed_default_tariffs(db)

        await db.commit()

    logger.info("🎉 Seed completo!")


if __name__ == "__main__":
    asyncio.run(main())
