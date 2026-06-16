from datetime import datetime

from pydantic import BaseModel, field_validator


class SystemSettingResponse(BaseModel):
    route_window_enabled: bool
    route_window_days_before_due: int
    route_window_days_after_due: int
    daily_interest_percent: float
    late_fee_percent: float
    installation_fee_amount: float
    reconnection_fee_amount: float
    cut_notice_days_after_due: int
    default_due_day: int
    auto_send_invoice_on_approval: bool = True
    notification_flows: dict = {}
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class SystemSettingUpdate(BaseModel):
    route_window_enabled: bool
    route_window_days_before_due: int
    route_window_days_after_due: int
    daily_interest_percent: float = 0.033
    late_fee_percent: float = 10.0
    installation_fee_amount: float = 100.0
    reconnection_fee_amount: float = 160.0
    cut_notice_days_after_due: int = 5
    default_due_day: int = 10
    auto_send_invoice_on_approval: bool = True
    notification_flows: dict = {}

    @field_validator("route_window_days_before_due", "route_window_days_after_due", "cut_notice_days_after_due")
    @classmethod
    def validate_days(cls, value: int) -> int:
        if not 0 <= value <= 28:
            raise ValueError("Os dias da janela devem ficar entre 0 e 28")
        return value

    @field_validator("default_due_day")
    @classmethod
    def validate_default_due_day(cls, value: int) -> int:
        if not 1 <= value <= 28:
            raise ValueError("Dia padrao de vencimento deve ficar entre 1 e 28")
        return value

    @field_validator("daily_interest_percent", "late_fee_percent")
    @classmethod
    def validate_percent(cls, value: float) -> float:
        if not 0 <= value <= 100:
            raise ValueError("Percentual deve ficar entre 0 e 100")
        return value

    @field_validator("installation_fee_amount", "reconnection_fee_amount")
    @classmethod
    def validate_amount(cls, value: float) -> float:
        if value < 0:
            raise ValueError("Valor nao pode ser negativo")
        return value
