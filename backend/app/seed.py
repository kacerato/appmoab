"""
AquaMoab - script de seed para dados iniciais.
"""

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy import text

from app.database import Base, async_session_factory, engine
from app.models import *  # noqa: F401, F403
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.services.billing import seed_default_tariffs
from app.services.hydrometer_codes import ensure_numeric_hydrometer_codes
from app.utils.security import hash_password

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ADMIN_EMAIL = "admin@aquamoab.com"
ADMIN_PASSWORD = "admin123"


async def main():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(text("ALTER TABLE hydrometers ADD COLUMN IF NOT EXISTS red_digits INTEGER NOT NULL DEFAULT 3"))
        await conn.execute(text("ALTER TABLE hydrometers ADD COLUMN IF NOT EXISTS black_digits INTEGER"))
        await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS red_digits INTEGER"))
        await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS black_digits INTEGER"))
        await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS hydrometer_brand VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS hydrometer_model VARCHAR(100)"))
        await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS reasoning_log TEXT"))
        await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS divergence_reason TEXT"))
    logger.info("Tabelas criadas/verificadas")

    async with async_session_factory() as db:
        result = await db.execute(select(User).where(User.email == ADMIN_EMAIL))
        if not result.scalar_one_or_none():
            admin = User(
                name="Administrador",
                email=ADMIN_EMAIL,
                password_hash=hash_password(ADMIN_PASSWORD),
                role="admin",
            )
            db.add(admin)
            logger.info("Admin criado: %s / %s", ADMIN_EMAIL, ADMIN_PASSWORD)
        else:
            logger.info("Admin ja existe")

        await seed_default_tariffs(db)

        from app.models.deduction import Deduction

        deductions_result = await db.execute(select(Deduction))
        if not deductions_result.scalars().first():
            db.add_all(
                [
                    Deduction(label="Despesa operacional", amount=2000.0, sort_order=0),
                    Deduction(label="Manutencao", amount=350.0, sort_order=1),
                    Deduction(label="Energia", amount=600.0, sort_order=2),
                    Deduction(label="Outros", amount=150.0, sort_order=3),
                ]
            )
            logger.info("Deducoes padrao criadas")
        else:
            logger.info("Deducoes ja existem")

        settings_result = await db.execute(select(SystemSetting).where(SystemSetting.id == 1))
        if not settings_result.scalar_one_or_none():
            db.add(SystemSetting(id=1))
            logger.info("Configuracoes do sistema criadas")

        updated_hydrometers = await ensure_numeric_hydrometer_codes(db)
        if updated_hydrometers:
            logger.info("%s hidrometro(s) antigos migrados para codigo numerico", updated_hydrometers)

        await db.commit()

    logger.info("Seed completo")


if __name__ == "__main__":
    asyncio.run(main())
