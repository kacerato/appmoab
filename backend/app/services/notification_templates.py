"""Mensagens configuraveis de notificacao."""

from string import Formatter
from typing import Any
from datetime import date

from app.models.system_setting import SystemSetting


DEFAULT_NOTIFICATION_FLOWS: dict[str, dict[str, Any]] = {
    "invoice_generated": {
        "enabled": True,
        "message": "Olá, sua fatura foi gerada. Consulte o valor e o vencimento no atendimento.",
    },
    "reminder_before_due": {
        "enabled": True,
        "days": 5,
        "message": "Olá, sua fatura vence em breve. Evite atraso fazendo o pagamento até o vencimento.",
    },
    "due_today": {
        "enabled": True,
        "message": "Olá, sua fatura vence hoje. Se já pagou, desconsidere esta mensagem.",
    },
    "overdue": {
        "enabled": True,
        "days": 1,
        "message": "Olá, identificamos uma fatura em atraso. Regularize para evitar bloqueios.",
    },
    "payment_confirmed": {
        "enabled": True,
        "message": "Pagamento confirmado. Obrigado!",
    },
}

FLOW_NOTIFICATION_TYPES = {
    "invoice_generated": "invoice_generated",
    "reminder_before_due": "reminder_5d",
    "due_today": "due_today",
    "overdue": "overdue_1d",
    "payment_confirmed": "payment_confirmed",
}


def get_notification_flow(settings: SystemSetting | None, flow_key: str) -> dict[str, Any]:
    default = DEFAULT_NOTIFICATION_FLOWS.get(flow_key, {"enabled": True, "message": ""})
    configured = {}
    if settings and isinstance(settings.notification_flows, dict):
        configured = settings.notification_flows.get(flow_key) or {}
    return {**default, **configured}


def notification_flow_enabled(settings: SystemSetting | None, flow_key: str) -> bool:
    return bool(get_notification_flow(settings, flow_key).get("enabled", True))


def render_notification_message(
    settings: SystemSetting | None,
    flow_key: str,
    params: dict[str, Any],
) -> str:
    flow = get_notification_flow(settings, flow_key)
    template = str(flow.get("message") or DEFAULT_NOTIFICATION_FLOWS.get(flow_key, {}).get("message") or "")
    if not template:
        return ""

    placeholders = {field for _, field, _, _ in Formatter().parse(template) if field}
    if not placeholders:
        return template
    safe_params = {key: str(value) for key, value in params.items()}
    return template.format_map(_SafeDict(safe_params))


def render_invoice_customer_message(
    settings: SystemSetting | None,
    *,
    charge_type: str,
    customer_name: str,
    amount: float,
    due_date: date,
    reference_month: str,
) -> str:
    formatted_amount = f"R$ {amount:.2f}".replace(".", ",")
    formatted_due = due_date.strftime("%d/%m/%Y")
    if charge_type == "installation":
        return (
            f"Olá {customer_name}, sua cobrança de instalação do hidrômetro "
            f"no valor de {formatted_amount} vence em {formatted_due}."
        )
    if charge_type == "reconnection":
        return (
            f"Olá {customer_name}, sua cobrança de religação "
            f"no valor de {formatted_amount} vence em {formatted_due}."
        )
    if charge_type == "manual":
        return (
            f"Olá {customer_name}, sua cobrança avulsa "
            f"no valor de {formatted_amount} vence em {formatted_due}."
        )

    return render_notification_message(settings, "invoice_generated", {
        "nome": customer_name,
        "valor": formatted_amount,
        "data_vencimento": formatted_due,
        "referencia": reference_month,
    })


class _SafeDict(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"
