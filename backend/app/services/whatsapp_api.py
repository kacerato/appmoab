"""
AquaMoab — Serviço WhatsApp Cloud API (preparado, ativação via flag).
"""

import logging
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class WhatsAppService:
    """Cliente WhatsApp Cloud API — ativado via WHATSAPP_ENABLED."""

    TEMPLATES = {
        "reminder_5d": {
            "name": "fatura_vencimento_proximo",
            "language": "pt_BR",
            "params": ["nome", "valor", "data_vencimento"],
        },
        "due_today": {
            "name": "fatura_vence_hoje",
            "language": "pt_BR",
            "params": ["nome", "valor"],
        },
        "overdue_1d": {
            "name": "fatura_atrasada",
            "language": "pt_BR",
            "params": ["nome", "valor"],
        },
        "payment_confirmed": {
            "name": "pagamento_confirmado",
            "language": "pt_BR",
            "params": ["nome", "valor"],
        },
    }

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    @property
    def is_enabled(self) -> bool:
        return settings.whatsapp_enabled and bool(settings.whatsapp_token)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=settings.whatsapp_base_url,
                timeout=30.0,
                headers={
                    "Authorization": f"Bearer {settings.whatsapp_token}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def send_template(
        self,
        phone: str,
        template_key: str,
        params: dict,
    ) -> dict | None:
        """
        Envia template de mensagem via WhatsApp.
        Retorna None se WhatsApp estiver desabilitado.
        """
        if not self.is_enabled:
            logger.info(f"WhatsApp desabilitado — template '{template_key}' não enviado para {phone}")
            return None

        template_config = self.TEMPLATES.get(template_key)
        if not template_config:
            raise ValueError(f"Template desconhecido: {template_key}")

        # Formata número (BR: +55)
        digits = "".join(c for c in phone if c.isdigit())
        if not digits.startswith("55"):
            digits = f"55{digits}"

        # Monta componentes do template
        components = [{
            "type": "body",
            "parameters": [
                {"type": "text", "text": str(params.get(p, ""))}
                for p in template_config["params"]
            ],
        }]

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": digits,
            "type": "template",
            "template": {
                "name": template_config["name"],
                "language": {"code": template_config["language"]},
                "components": components,
            },
        }

        client = await self._get_client()

        try:
            response = await client.post(
                f"/{settings.whatsapp_phone_id}/messages",
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
            message_id = data.get("messages", [{}])[0].get("id")
            logger.info(f"WhatsApp enviado: {message_id} → {digits}")
            return {"message_id": message_id, "status": "sent"}
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro WhatsApp: {e.response.text}")
            return {"message_id": None, "status": "failed", "error": e.response.text}

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


whatsapp_service = WhatsAppService()
