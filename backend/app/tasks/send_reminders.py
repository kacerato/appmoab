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
    _run_async(_send_reminders_async("reminder_before_due", days_before=5))


@celery_app.task(name="app.tasks.send_reminders.send_due_today_reminders")
def send_due_today_reminders():
    """Envia lembrete no dia do vencimento."""
    _run_async(_send_reminders_async("due_today", days_before=0))


@celery_app.task(name="app.tasks.send_reminders.send_overdue_reminders")
def send_overdue_reminders():
    """Envia lembrete 1 dia após vencimento."""
    _run_async(_send_reminders_async("overdue", days_after=1))


async def _send_reminders_async(
    flow_key: str,
    days_before: int = 0,
    days_after: int = 0,
):
    from app.database import async_session_factory
    from app.models.invoice import Invoice
    from app.models.customer import Customer
    from app.models.notification import Notification
    from app.models.system_setting import SystemSetting
    from app.models.whatsapp_message import WhatsAppMessage
    from app.services.notification_templates import (
        FLOW_NOTIFICATION_TYPES,
        get_notification_flow,
        notification_flow_enabled,
        render_notification_message,
    )
    from app.services.whatsapp_api import whatsapp_service
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from datetime import datetime, timezone

    async with async_session_factory() as db:
        settings = (await db.execute(select(SystemSetting).where(SystemSetting.id == 1))).scalar_one_or_none()
        if not notification_flow_enabled(settings, flow_key):
            logger.info("[%s] fluxo desativado nas configuracoes", flow_key)
            return

        flow = get_notification_flow(settings, flow_key)
        configured_days = int(flow.get("days") or 0)
        if flow_key == "reminder_before_due":
            days_before = configured_days or days_before
        elif flow_key == "overdue":
            days_after = configured_days or days_after

        notification_type = FLOW_NOTIFICATION_TYPES[flow_key]

        if days_before > 0:
            target_date = date.today() + timedelta(days=days_before)
            status_filter = ["sent", "pending"]
        elif days_after > 0:
            target_date = date.today() - timedelta(days=days_after)
            status_filter = ["overdue"]
        else:
            target_date = date.today()
            status_filter = ["sent", "pending"]

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

            params = {
                "nome": customer.name,
                "valor": f"R$ {invoice.amount:.2f}",
                "data_vencimento": invoice.due_date.strftime("%d/%m/%Y"),
            }
            message = render_notification_message(settings, flow_key, params)

            notification = Notification(
                customer_id=customer.id,
                invoice_id=invoice.id,
                channel="whatsapp",
                type=notification_type,
                status="queued",
                payload={
                    "flow_key": flow_key,
                    "message": message,
                    "nome": customer.name,
                    "valor": f"R$ {invoice.amount:.2f}",
                    "data_vencimento": invoice.due_date.isoformat(),
                },
            )

            wa_result = await whatsapp_service.send_text(phone=customer.phone, text=message)

            if wa_result:
                notification.status = wa_result.get("status", "failed")
                notification.external_message_id = wa_result.get("message_id")
                notification.sent_at = datetime.now(timezone.utc)
                if wa_result.get("error"):
                    notification.error_message = wa_result["error"][:500]
                elif notification.status == "sent":
                    db.add(WhatsAppMessage(
                        customer_id=customer.id,
                        phone=whatsapp_service.normalize_phone(customer.phone),
                        direction="outbound",
                        body=message,
                        external_message_id=notification.external_message_id,
                        status="sent",
                        payload={"flow_key": flow_key, "invoice_id": str(invoice.id)},
                    ))
            else:
                notification.status = "failed"
                notification.error_message = "WhatsApp desabilitado ou sem canal ativo"

            db.add(notification)

        await db.commit()
