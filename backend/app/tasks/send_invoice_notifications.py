"""Retries duraveis das faturas pendentes de WhatsApp."""

import asyncio

from app.services.invoice_whatsapp import dispatch_due_invoice_notifications
from app.tasks.celery_app import celery_app


@celery_app.task(name="app.tasks.send_invoice_notifications.retry_invoice_notifications")
def retry_invoice_notifications():
    return asyncio.run(dispatch_due_invoice_notifications())
