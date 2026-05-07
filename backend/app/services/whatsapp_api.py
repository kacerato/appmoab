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

    async def send_invoice_document(
        self,
        phone: str,
        pdf_data: bytes,
        filename: str,
        caption: str = ""
    ) -> dict | None:
        """
        Envia a fatura em PDF diretamente para o WhatsApp do cliente.
        Fluxo: Faz upload do Media (PDF) para a API do WhatsApp, e em seguida
        envia a mensagem do tipo 'document' contendo o media_id.
        """
        if not self.is_enabled:
            logger.info(f"WhatsApp desabilitado — PDF da fatura não enviado para {phone}")
            return None

        digits = "".join(c for c in phone if c.isdigit())
        if not digits.startswith("55"):
            digits = f"55{digits}"

        client = await self._get_client()

        try:
            # 1. Upload do Media (PDF)
            # Para WhatsApp Cloud API o upload é feito como multipart/form-data
            media_payload = {
                "messaging_product": "whatsapp"
            }
            files = {
                "file": (filename, pdf_data, "application/pdf")
            }
            
            # Precisamos recriar o client para usar FormData corretamente sem header Content-Type hardcoded
            upload_client = httpx.AsyncClient(
                base_url=settings.whatsapp_base_url,
                timeout=30.0,
                headers={"Authorization": f"Bearer {settings.whatsapp_token}"}
            )
            
            upload_resp = await upload_client.post(
                f"/{settings.whatsapp_phone_id}/media",
                data=media_payload,
                files=files
            )
            upload_resp.raise_for_status()
            media_id = upload_resp.json().get("id")
            await upload_client.aclose()

            if not media_id:
                raise ValueError("Falha ao obter media_id do WhatsApp")

            # 2. Enviar a Mensagem (Document) com o media_id
            msg_payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": digits,
                "type": "document",
                "document": {
                    "id": media_id,
                    "caption": caption,
                    "filename": filename
                }
            }

            msg_resp = await client.post(
                f"/{settings.whatsapp_phone_id}/messages",
                json=msg_payload,
            )
            msg_resp.raise_for_status()
            message_id = msg_resp.json().get("messages", [{}])[0].get("id")
            
            logger.info(f"Fatura PDF enviada via WhatsApp para {digits} (Msg ID: {message_id})")
            return {"message_id": message_id, "status": "sent"}

        except httpx.HTTPStatusError as e:
            logger.error(f"Erro WhatsApp Document: {e.response.text}")
            return {"message_id": None, "status": "failed", "error": e.response.text}
        except Exception as e:
            logger.error(f"Erro geral WhatsApp Document: {e}")
            return {"message_id": None, "status": "failed", "error": str(e)}

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


whatsapp_service = WhatsAppService()
