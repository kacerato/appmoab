"""
AquaMoab — Serviço WhatsApp Local (via Evolution API).
"""

import logging
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class WhatsAppService:
    """Cliente WhatsApp que se comunica com a Evolution API."""

    def __init__(self):
        self._client: httpx.AsyncClient | None = None

    @property
    def is_enabled(self) -> bool:
        return settings.whatsapp_enabled

    @staticmethod
    def normalize_phone(phone: str) -> str:
        digits = "".join(c for c in phone if c.isdigit())
        if not digits:
            return ""
        if not digits.startswith("55"):
            digits = f"55{digits}"
        return digits

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=settings.evolution_api_url,
                timeout=30.0,
                headers={
                    "Content-Type": "application/json",
                    "apikey": settings.evolution_api_key
                },
            )
        return self._client

    async def send_template(
        self,
        phone: str,
        template_key: str,
        params: dict,
    ) -> dict | None:
        if not self.is_enabled:
            logger.info(f"WhatsApp desabilitado — template '{template_key}' não enviado para {phone}")
            return None

        # Formata número (BR: +55)
        digits = self.normalize_phone(phone)

        # Simula o texto dos templates
        text_message = ""
        if template_key == "reminder_5d":
            text_message = f"Olá {params.get('nome')}, passando para lembrar que a fatura no valor de R$ {params.get('valor')} vence no dia {params.get('data_vencimento')}."
        elif template_key == "due_today":
            text_message = f"Olá {params.get('nome')}, sua fatura no valor de R$ {params.get('valor')} vence HOJE."
        elif template_key == "overdue_1d":
            text_message = f"Olá {params.get('nome')}, não identificamos o pagamento da fatura de R$ {params.get('valor')}. Por favor desconsidere se já pagou."
        elif template_key == "payment_confirmed":
            text_message = f"Olá {params.get('nome')}, confirmamos o recebimento do pagamento de R$ {params.get('valor')}. Obrigado!"
        else:
            text_message = f"Mensagem automática: {template_key} - {params}"

        client = await self._get_client()

        try:
            response = await client.post(
                f"/message/sendText/{settings.evolution_instance_name}",
                json={"number": digits, "text": text_message},
            )
            response.raise_for_status()
            logger.info(f"WhatsApp (Evolution API) enviado para {digits}")
            payload = response.json() if response.content else {}
            return {"status": "sent", "message_id": payload.get("key", {}).get("id")}
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro Evolution API: {e.response.text}")
            return {"status": "failed", "error": e.response.text}
        except Exception as e:
            logger.error(f"Erro ao conectar com Evolution API: {e}")
            return {"status": "failed", "error": str(e)}

    async def send_text(self, phone: str, text: str, quoted: dict | None = None) -> dict | None:
        if not self.is_enabled:
            return None

        digits = self.normalize_phone(phone)
        payload: dict = {"number": digits, "text": text}
        if quoted:
            payload["quoted"] = quoted

        client = await self._get_client()
        try:
            response = await client.post(
                f"/message/sendText/{settings.evolution_instance_name}",
                json=payload,
            )
            response.raise_for_status()
            logger.info(f"WhatsApp (Evolution API) enviado para {digits}")
            response_payload = response.json() if response.content else {}
            return {
                "status": "sent",
                "message_id": response_payload.get("key", {}).get("id"),
                "payload": response_payload,
            }
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro Evolution API: {e.response.text}")
            return {"status": "failed", "error": e.response.text}
        except Exception as e:
            logger.error(f"Erro ao conectar com Evolution API: {e}")
            return {"status": "failed", "error": str(e)}

    async def send_invoice_document(
        self,
        phone: str,
        pdf_data: bytes,
        filename: str,
        caption: str = ""
    ) -> dict | None:
        """
        Envia PDF em formato Base64 para a Evolution API.
        """
        import base64
        
        if not self.is_enabled:
            return None

        digits = self.normalize_phone(phone)

        client = await self._get_client()
        base64_pdf = base64.b64encode(pdf_data).decode('utf-8')

        try:
            response = await client.post(
                f"/message/sendMedia/{settings.evolution_instance_name}",
                json={
                    "number": digits,
                    "mediatype": "document",
                    "media": base64_pdf,
                    "fileName": filename,
                    "caption": caption
                },
            )
            response.raise_for_status()
            logger.info(f"Fatura PDF (Evolution API) enviada para {digits}")
            payload = response.json() if response.content else {}
            return {"status": "sent", "message_id": payload.get("key", {}).get("id")}
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro ao enviar doc Evolution API: {e.response.text}")
            return {"status": "failed", "error": e.response.text}
        except Exception as e:
            logger.error(f"Erro geral ao enviar doc: {e}")
            return {"status": "failed", "error": str(e)}

    async def send_media(
        self,
        *,
        phone: str,
        media_base64: str,
        filename: str,
        caption: str = "",
        mediatype: str = "document",
        mimetype: str | None = None,
        quoted: dict | None = None,
    ) -> dict | None:
        if not self.is_enabled:
            return None

        digits = self.normalize_phone(phone)
        payload: dict = {
            "number": digits,
            "mediatype": mediatype,
            "media": media_base64.split(",", 1)[1] if media_base64.startswith("data:") and "," in media_base64 else media_base64,
            "fileName": filename,
            "caption": caption,
        }
        if mimetype:
            payload["mimetype"] = mimetype
        if quoted:
            payload["quoted"] = quoted

        client = await self._get_client()
        try:
            response = await client.post(
                f"/message/sendMedia/{settings.evolution_instance_name}",
                json=payload,
            )
            response.raise_for_status()
            response_payload = response.json() if response.content else {}
            return {
                "status": "sent",
                "message_id": response_payload.get("key", {}).get("id"),
                "payload": response_payload,
            }
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro ao enviar midia Evolution API: {e.response.text}")
            return {"status": "failed", "error": e.response.text}
        except Exception as e:
            logger.error(f"Erro geral ao enviar midia: {e}")
            return {"status": "failed", "error": str(e)}

    async def get_media_base64(self, message: dict, convert_to_mp4: bool = False) -> dict | None:
        if not self.is_enabled:
            return {"status": "disabled", "error": "WhatsApp desabilitado"}

        client = await self._get_client()
        try:
            response = await client.post(
                f"/chat/getBase64FromMediaMessage/{settings.evolution_instance_name}",
                json={"message": message, "convertToMp4": convert_to_mp4},
            )
            response.raise_for_status()
            payload = response.json() if response.content else {}
            return {"status": "ok", "payload": payload}
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro Evolution API ao buscar midia: {e.response.text}")
            return {"status": "failed", "error": e.response.text}
        except Exception as e:
            logger.error(f"Erro ao buscar midia na Evolution API: {e}")
            return {"status": "failed", "error": str(e)}

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


whatsapp_service = WhatsAppService()
