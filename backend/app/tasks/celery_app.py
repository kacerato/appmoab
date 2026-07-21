"""
AquaMoab — Configuração do Celery para tarefas assíncronas.
"""

from celery import Celery
from celery.schedules import crontab
from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "aquamoab",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.check_payments",
        "app.tasks.send_reminders",
        "app.tasks.send_invoice_notifications",
    ],
)

celery_app.conf.update(
    timezone="America/Manaus",
    enable_utc=True,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    worker_max_tasks_per_child=1000,
)

# Agendamento de tarefas
celery_app.conf.beat_schedule = {
    "check-payments-daily": {
        "task": "app.tasks.check_payments.check_payment_status",
        "schedule": crontab(hour=8, minute=0),
    },
    "mark-overdue-daily": {
        "task": "app.tasks.check_payments.mark_overdue_invoices",
        "schedule": crontab(hour=0, minute=30),
    },
    "generate-fixed-invoices-monthly": {
        "task": "app.tasks.check_payments.generate_fixed_invoices",
        "schedule": crontab(day_of_month=1, hour=6, minute=0),
    },
    "send-reminder-5d": {
        "task": "app.tasks.send_reminders.send_5day_reminders",
        "schedule": crontab(hour=9, minute=0),
    },
    "send-reminder-due-today": {
        "task": "app.tasks.send_reminders.send_due_today_reminders",
        "schedule": crontab(hour=8, minute=0),
    },
    "send-reminder-overdue": {
        "task": "app.tasks.send_reminders.send_overdue_reminders",
        "schedule": crontab(hour=10, minute=0),
    },
    "retry-invoice-whatsapp": {
        "task": "app.tasks.send_invoice_notifications.retry_invoice_notifications",
        "schedule": crontab(minute="*/2"),
    },
}
