"""
Tasks de envio de lembretes — preparado para WhatsApp (flag on/off).
"""

import asyncio
import logging
from datetime import date, timedelta

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@celery_app.task(name="app.tasks.send_reminders.send_5day_reminders")
def send_5day_reminders():
    """Envia lembrete 5 dias antes do vencimento."""
    _run_async(_send_reminders_async("reminder_5d", days_before=5))


@celery_app.task(name="app.tasks.send_reminders.send_due_today_reminders")
def send_due_today_reminders():
    """Envia lembrete no dia do vencimento."""
    _run_async(_send_reminders_async("due_today", days_before=0))


@celery_app.task(name="app.tasks.send_reminders.send_overdue_reminders")
def send_overdue_reminders():
    """Envia lembrete 1 dia após vencimento."""
    _run_async(_send_reminders_async("overdue_1d", days_after=1))


async def _send_reminders_async(
    notification_type: str,
    days_before: int = 0,
    days_after: int = 0,
):
    from app.database import async_session_factory
    from app.models.invoice import Invoice
    from app.models.customer import Customer
    from app.models.notification import Notification
    from app.services.whatsapp_api import whatsapp_service
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from datetime import datetime, timezone

    if days_before > 0:
        target_date = date.today() + timedelta(days=days_before)
        status_filter = ["sent", "pending"]
    elif days_after > 0:
        target_date = date.today() - timedelta(days=days_after)
        status_filter = ["overdue"]
    else:
        target_date = date.today()
        status_filter = ["sent", "pending"]

    async with async_session_factory() as db:
        result = await db.execute(
            select(Invoice)
            .options(selectinload(Invoice.customer))
            .where(
                Invoice.due_date == target_date,
                Invoice.status.in_(status_filter),
            )
        )
        invoices = result.scalars().all()

        logger.info(f"[{notification_type}] {len(invoices)} faturas encontradas para {target_date}")

        for invoice in invoices:
            customer = invoice.customer
            if not customer or not customer.phone:
                continue

            # Verifica se já enviou esse tipo de notificação
            existing = await db.execute(
                select(Notification).where(
                    Notification.invoice_id == invoice.id,
                    Notification.type == notification_type,
                    Notification.status.in_(["sent", "delivered"]),
                )
            )
            if existing.scalar_one_or_none():
                continue

            # Cria registro de notificação
            notification = Notification(
                customer_id=customer.id,
                invoice_id=invoice.id,
                channel="whatsapp",
                type=notification_type,
                status="queued",
                payload={
                    "nome": customer.name,
                    "valor": f"R$ {invoice.amount:.2f}",
                    "data_vencimento": invoice.due_date.isoformat(),
                },
            )

            # Envia se WhatsApp ativado
            wa_result = await whatsapp_service.send_template(
                phone=customer.phone,
                template_key=notification_type,
                params={
                    "nome": customer.name,
                    "valor": f"R$ {invoice.amount:.2f}",
                    "data_vencimento": invoice.due_date.strftime("%d/%m/%Y"),
                },
            )

            if wa_result:
                notification.status = wa_result.get("status", "failed")
                notification.external_message_id = wa_result.get("message_id")
                notification.sent_at = datetime.now(timezone.utc)
                if wa_result.get("error"):
                    notification.error_message = wa_result["error"][:500]
            else:
                notification.status = "failed"
                notification.error_message = "WhatsApp desabilitado ou sem canal ativo"

            db.add(notification)

        await db.commit()
