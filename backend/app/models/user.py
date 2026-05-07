"""
Modelo de Usuário — Administradores e Colaboradores do sistema.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, Boolean, Enum as SAEnum, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        SAEnum("admin", "collaborator", name="user_role_enum", create_constraint=True),
        nullable=False,
        default="collaborator",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationships
    readings_captured = relationship("Reading", back_populates="collaborator", foreign_keys="Reading.collaborator_id")
    readings_approved = relationship("Reading", back_populates="approver", foreign_keys="Reading.approved_by")

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"
