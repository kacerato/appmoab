"""Exporta todos os modelos para Alembic e imports simplificados."""

from app.models.user import User
from app.models.customer import Customer
from app.models.hydrometer import Hydrometer
from app.models.reading import Reading
from app.models.invoice import Invoice
from app.models.tariff import TariffTier
from app.models.notification import Notification
from app.models.whatsapp_message import WhatsAppMessage
from app.models.kimi_memory import KimiVisionMemory
from app.models.deduction import Deduction
from app.models.customer_attachment import CustomerAttachment
from app.models.system_setting import SystemSetting

__all__ = [
    "User",
    "Customer",
    "Hydrometer",
    "Reading",
    "Invoice",
    "TariffTier",
    "Notification",
    "KimiVisionMemory",
    "Deduction",
    "CustomerAttachment",
    "SystemSetting",
]
