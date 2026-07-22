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

    @staticmethod
    def _provider_failure(exc: Exception, *, action: str = "enviar a mensagem") -> dict:
        """Converte detalhes internos da Evolution em um contrato seguro para a UI."""
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code
            raw = exc.response.text or ""
            normalized = raw.lower()
            logger.warning(
                "Evolution recusou a operacao %s (HTTP %s): %s",
                action,
                status_code,
                raw[:1000],
            )
            if status_code == 429 or any(term in normalized for term in ("rate limit", "too many", "temporarily restricted")):
                return {
                    "status": "failed",
                    "error_code": "rate_limited",
                    "error": "O WhatsApp limitou temporariamente os envios. Aguarde antes de tentar novamente.",
                }
            if status_code == 403 or any(term in normalized for term in ("restricted", "restriction", "suspended", "blocked", "temporarily banned")):
                return {
                    "status": "failed",
                    "error_code": "account_restricted",
                    "error": "A conta do WhatsApp está temporariamente restrita. Os envios foram pausados.",
                }
            if any(term in normalized for term in ("connection closed", "not connected", "disconnected", "instance is not open", "connection close")):
                return {
                    "status": "failed",
                    "error_code": "whatsapp_disconnected",
                    "error": "WhatsApp desconectado. Conecte o número pelo QR Code no dashboard antes de enviar.",
                }
            return {
                "status": "failed",
                "error_code": "provider_rejected",
                "error": f"O WhatsApp não conseguiu {action} agora. Tente novamente em alguns instantes.",
            }

        logger.warning("Falha de comunicacao com a Evolution ao %s: %s", action, exc)
        return {
            "status": "failed",
            "error_code": "provider_unavailable",
            "error": "O serviço do WhatsApp está temporariamente indisponível. Tente novamente em alguns instantes.",
        }

    async def health(self) -> dict:
        """Consulta a sessao real da Evolution sem expor URL, chave ou instancia."""
        configured = bool(
            settings.whatsapp_enabled
            and settings.evolution_api_url
            and settings.evolution_api_key
            and settings.evolution_instance_name
        )
        result = {
            "enabled": settings.whatsapp_enabled,
            "configured": configured,
            "reachable": False,
            "connected": False,
            "instance_state": "disabled" if not settings.whatsapp_enabled else "unknown",
            "error": None,
        }
        if not configured:
            result["error"] = "Configuracao da Evolution incompleta."
            return result

        try:
            client = await self._get_client()
            response = await client.get(f"/instance/connectionState/{settings.evolution_instance_name}")
            response.raise_for_status()
            payload = response.json() if response.content else {}
            instance = payload.get("instance") if isinstance(payload.get("instance"), dict) else {}
            state = str(instance.get("state") or payload.get("state") or "unknown").lower()
            result.update({
                "reachable": True,
                "connected": state in {"open", "connected"},
                "instance_state": state,
            })
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "Evolution recusou a consulta de estado (HTTP %s): %s",
                exc.response.status_code,
                exc.response.text[:1000],
            )
            result["error"] = "Não foi possível verificar a conexão do WhatsApp agora."
        except Exception as exc:
            logger.warning("Falha ao consultar estado da Evolution: %s", exc)
            result["error"] = "Nao foi possivel consultar a Evolution."
        return result

    async def connection_qr(self) -> dict:
        """Obtém o QR da instância sem expor credenciais ou respostas brutas."""
        health = await self.health()
        if health["connected"]:
            return {
                "status": "connected",
                "connected": True,
                "detail": "WhatsApp já está conectado.",
                "base64": None,
                "pairing_code": None,
            }
        if not health["configured"]:
            return {
                "status": "unavailable",
                "connected": False,
                "detail": "A integração do WhatsApp ainda não foi configurada.",
                "base64": None,
                "pairing_code": None,
            }

        try:
            client = await self._get_client()
            response = await client.get(f"/instance/connect/{settings.evolution_instance_name}")
            response.raise_for_status()
            payload = response.json() if response.content else {}
            qrcode = payload.get("qrcode") if isinstance(payload.get("qrcode"), dict) else {}
            qr = payload.get("qr") if isinstance(payload.get("qr"), dict) else {}
            base64_image = payload.get("base64") or qrcode.get("base64") or qr.get("base64")
            pairing_code = payload.get("pairingCode") or payload.get("pairing_code") or qrcode.get("code") or qr.get("code")
            if base64_image and not str(base64_image).startswith("data:image"):
                base64_image = f"data:image/png;base64,{base64_image}"
            if not base64_image and not pairing_code:
                return {
                    "status": "waiting",
                    "connected": False,
                    "detail": "O QR Code ainda está sendo preparado. Tente atualizar em alguns segundos.",
                    "base64": None,
                    "pairing_code": None,
                }
            return {
                "status": "qr_ready",
                "connected": False,
                "detail": "Escaneie este QR Code no WhatsApp para conectar o número.",
                "base64": base64_image,
                "pairing_code": pairing_code,
            }
        except Exception as exc:
            failure = self._provider_failure(exc, action="gerar o QR Code")
            return {
                "status": "unavailable",
                "connected": False,
                "detail": failure["error"],
                "base64": None,
                "pairing_code": None,
            }

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
        except Exception as exc:
            return self._provider_failure(exc)

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
        except Exception as exc:
            return self._provider_failure(exc)

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
        except Exception as exc:
            return self._provider_failure(exc, action="enviar a fatura")

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
        except Exception as exc:
            return self._provider_failure(exc, action="enviar a mídia")

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
        except Exception as exc:
            return self._provider_failure(exc, action="carregar a mídia")

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


whatsapp_service = WhatsAppService()
