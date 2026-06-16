from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    route_window_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    route_window_days_before_due: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    route_window_days_after_due: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    daily_interest_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.033)
    late_fee_percent: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)
    installation_fee_amount: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    reconnection_fee_amount: Mapped[float] = mapped_column(Float, nullable=False, default=160.0)
    cut_notice_days_after_due: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    default_due_day: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    auto_send_invoice_on_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notification_flows: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
