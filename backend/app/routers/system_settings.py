from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.system_setting import SystemSetting
from app.models.user import User
from app.schemas.system_setting import SystemSettingResponse, SystemSettingUpdate
from app.services.efi_api import EfiAPIError, efi_service
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
    settings.daily_interest_percent = data.daily_interest_percent
    settings.late_fee_percent = data.late_fee_percent
    settings.installation_fee_amount = data.installation_fee_amount
    settings.reconnection_fee_amount = data.reconnection_fee_amount
    settings.cut_notice_days_after_due = data.cut_notice_days_after_due
    settings.default_due_day = data.default_due_day
    settings.auto_send_invoice_on_approval = data.auto_send_invoice_on_approval
    settings.notification_flows = data.notification_flows
    await db.flush()
    await db.refresh(settings)
    return settings


@router.post("/efi/validate")
async def validate_efi_credentials(admin: User = Depends(require_admin)):
    try:
        return await efi_service.validar_autenticacao()
    except EfiAPIError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": exc.message,
                "status_code": exc.status_code,
                "detail": exc.detail,
            },
        ) from exc
