from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.schemas.system_setting import SystemSettingResponse, SystemSettingUpdate
from app.utils.security import get_current_user, require_admin

router = APIRouter(prefix="/system-settings", tags=["Configuracoes do Sistema"])


async def _get_or_create_system_settings(db: AsyncSession) -> SystemSetting:
    result = await db.execute(select(SystemSetting).where(SystemSetting.id == 1))
    settings = result.scalar_one_or_none()
    if settings:
        return settings

    settings = SystemSetting(id=1)
    db.add(settings)
    await db.flush()
    return settings


@router.get("", response_model=SystemSettingResponse)
async def get_system_settings(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await _get_or_create_system_settings(db)


@router.patch("", response_model=SystemSettingResponse)
async def update_system_settings(
    data: SystemSettingUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    settings = await _get_or_create_system_settings(db)
    settings.route_window_enabled = data.route_window_enabled
    settings.route_window_days_before_due = data.route_window_days_before_due
    settings.route_window_days_after_due = data.route_window_days_after_due
    await db.flush()
    await db.refresh(settings)
    return settings
