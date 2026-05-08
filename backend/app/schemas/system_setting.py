from datetime import datetime

from pydantic import BaseModel, field_validator


class SystemSettingResponse(BaseModel):
    route_window_enabled: bool
    route_window_days_before_due: int
    route_window_days_after_due: int
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class SystemSettingUpdate(BaseModel):
    route_window_enabled: bool
    route_window_days_before_due: int
    route_window_days_after_due: int

    @field_validator("route_window_days_before_due", "route_window_days_after_due")
    @classmethod
    def validate_days(cls, value: int) -> int:
        if not 0 <= value <= 28:
            raise ValueError("Os dias da janela devem ficar entre 0 e 28")
        return value
