"""Integracao com a API Cobranças Efí."""

import base64
import logging
import time
from datetime import date, timedelta
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class EfiAPIError(Exception):
    def __init__(self, message: str, status_code: int = 0, detail: Any = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


class EfiAPIService:
    def __init__(self) -> None:
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._client: httpx.AsyncClient | None = None

    def _assert_configured(self) -> None:
        if not settings.efi_client_id or not settings.efi_client_secret:
            raise EfiAPIError("Credenciais da Efí nao configuradas")
        if bool(settings.efi_cert_path) != bool(settings.efi_key_path):
            raise EfiAPIError("Configure EFI_CERT_PATH e EFI_KEY_PATH juntos ou deixe ambos vazios")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            cert = None
            if settings.efi_cert_path and settings.efi_key_path:
                cert = (settings.efi_cert_path, settings.efi_key_path)
            self._client = httpx.AsyncClient(
                base_url=settings.efi_cobrancas_base_url,
                timeout=30.0,
                cert=cert,
            )
        return self._client

    async def _get_token(self) -> str:
        self._assert_configured()
        if self._access_token and time.time() < self._token_expires_at - 30:
            return self._access_token

        client = await self._get_client()
        credentials = f"{settings.efi_client_id}:{settings.efi_client_secret}".encode()
        auth = base64.b64encode(credentials).decode()
        response = await client.post(
            "/v1/authorize",
            json={"grant_type": "client_credentials"},
            headers={
                "Authorization": f"Basic {auth}",
                "Content-Type": "application/json",
            },
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise EfiAPIError(
                "Falha na autenticacao com a Efí",
                status_code=exc.response.status_code,
                detail=_safe_json(exc.response),
            ) from exc

        data = response.json()
        access_token = data.get("access_token")
        if not access_token:
            raise EfiAPIError("Resposta de autenticacao da Efí sem access_token", detail=data)
        self._access_token = access_token
        self._token_expires_at = time.time() + int(data.get("expires_in") or 600)
        return self._access_token

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        token = await self._get_token()
        client = await self._get_client()
        headers = kwargs.pop("headers", {})
        headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        response = await client.request(method, path, headers=headers, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self._access_token = None
            raise EfiAPIError(
                "Falha na comunicacao com a Efí",
                status_code=exc.response.status_code,
                detail=_safe_json(exc.response),
            ) from exc
        return _safe_json(response) if response.content else {}

    async def validar_autenticacao(self) -> dict:
        """Valida credenciais/base URL sem emitir cobranca."""
        token = await self._get_token()
        return {
            "ok": True,
            "environment": "sandbox" if settings.efi_sandbox else "production",
            "base_url": settings.efi_cobrancas_base_url,
            "token_preview": f"{token[:8]}..." if token else "",
            "expires_at": int(self._token_expires_at),
        }

    async def emitir_cobranca(
        self,
        *,
        valor: float,
        cpf_cnpj: str,
        nome: str,
        email: str,
        telefone: str | None,
        endereco: str,
        numero: str,
        bairro: str,
        cidade: str,
        uf: str,
        cep: str,
        data_vencimento: date,
        seu_numero: str,
        mensagem: str = "",
        multa_percentual: float = 0.0,
        juros_diario_percentual: float = 0.0,
        dias_baixa_apos_vencimento: int | None = None,
    ) -> dict:
        cents = int(round(valor * 100))
        if cents <= 0:
            raise EfiAPIError("Valor da cobranca deve ser maior que zero")

        customer = self._build_customer(
            cpf_cnpj=cpf_cnpj,
            nome=nome,
            email=email,
            telefone=telefone,
            endereco=endereco,
            numero=numero,
            bairro=bairro,
            cidade=cidade,
            uf=uf,
            cep=cep,
        )
        configurations: dict[str, Any] = {
            "days_to_write_off": max(0, min(dias_baixa_apos_vencimento if dias_baixa_apos_vencimento is not None else settings.efi_boleto_days_to_write_off, 120)),
        }
        fine = int(round(max(0.0, multa_percentual) * 100))
        interest = int(round(max(0.0, juros_diario_percentual) * 1000))
        if fine:
            configurations["fine"] = fine
        if interest:
            configurations["interest"] = interest

        banking_billet = {
            "customer": customer,
            "expire_at": data_vencimento.isoformat(),
            "configurations": configurations,
            "message": _format_billet_message(mensagem),
        }
        payload: dict[str, Any] = {
            "items": [
                {
                    "name": _limit_message(seu_numero, 255) or "Fatura AquaMoab",
                    "value": cents,
                    "amount": 1,
                }
            ],
            "metadata": {
                "custom_id": seu_numero,
            },
            "payment": {
                "banking_billet": banking_billet,
            },
        }
        if settings.efi_notification_url:
            payload["metadata"]["notification_url"] = settings.efi_notification_url

        result = await self._request("POST", "/v1/charge/one-step", json=payload)
        return self._normalize_charge_response(result)

    async def consultar_cobranca(self, charge_id: str) -> dict:
        result = await self._request("GET", f"/v1/charge/{charge_id}")
        return self._normalize_charge_response(result)

    async def consultar_por_notificacao(self, token: str) -> dict:
        return await self._request("GET", f"/v1/notification/{token}")

    async def listar_cobrancas(
        self,
        *,
        statuses: list[str] | None = None,
        begin_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict]:
        end = end_date or date.today()
        begin = begin_date or (end - timedelta(days=90))
        params: dict[str, str] = {
            "charge_type": "billet",
            "begin_date": begin.isoformat(),
            "end_date": end.isoformat(),
        }
        if statuses:
            params["status"] = ",".join(statuses)
        result = await self._request("GET", "/v1/charges", params=params)
        data = result.get("data") or []
        return data if isinstance(data, list) else []

    async def baixar_pdf(self, pdf_url: str) -> bytes | None:
        if not pdf_url:
            return None
        client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        try:
            response = await client.get(pdf_url)
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            logger.warning("Falha ao baixar PDF Efí: %s", exc)
            return None
        finally:
            await client.aclose()

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _build_customer(self, **data) -> dict:
        digits = "".join(c for c in data["cpf_cnpj"] if c.isdigit())
        if len(digits) not in (11, 14):
            raise EfiAPIError("CPF/CNPJ do cliente invalido para emissao da cobranca Efí")
        zipcode = "".join(c for c in data["cep"] if c.isdigit())
        if len(zipcode) != 8:
            raise EfiAPIError("CEP do cliente invalido para emissao da cobranca Efí")
        uf = (data["uf"] or "").strip().upper()
        if len(uf) != 2:
            raise EfiAPIError("UF do cliente invalida para emissao da cobranca Efí")

        customer: dict[str, Any] = {
            "address": {
                "street": _required_text(data["endereco"], "endereco"),
                "number": data["numero"] or "S/N",
                "neighborhood": _required_text(data["bairro"], "bairro"),
                "zipcode": zipcode,
                "city": _required_text(data["cidade"], "cidade"),
                "complement": "",
                "state": uf,
            },
        }
        if data["email"]:
            customer["email"] = data["email"]
        phone = "".join(c for c in (data.get("telefone") or "") if c.isdigit())[:11]
        if len(phone) >= 10:
            customer["phone_number"] = phone
        if len(digits) == 14:
            customer["juridical_person"] = {"corporate_name": _required_text(data["nome"], "nome"), "cnpj": digits}
        else:
            customer["name"] = _required_text(data["nome"], "nome")
            customer["cpf"] = digits
        return customer

    def _normalize_charge_response(self, result: dict) -> dict:
        data = result.get("data") if isinstance(result.get("data"), dict) else result
        payment_value = data.get("payment") or {}
        payment = payment_value if isinstance(payment_value, dict) else {}
        billet_value = payment.get("banking_billet") or data.get("banking_billet") or {}
        billet = billet_value if isinstance(billet_value, dict) else {}
        pix_value = billet.get("pix") or data.get("pix") or {}
        pix = pix_value if isinstance(pix_value, dict) else {}
        pdf_value = billet.get("pdf") or data.get("pdf") or {}
        pdf = pdf_value if isinstance(pdf_value, dict) else {}
        return {
            "charge_id": str(data.get("charge_id") or data.get("id") or ""),
            "status": data.get("status"),
            "barcode": data.get("barcode") or billet.get("barcode"),
            "payment_url": data.get("payment_url") or data.get("billet_link") or data.get("link") or billet.get("link"),
            "pdf_url": pdf.get("charge") or data.get("pdf_url"),
            "pix_qrcode": pix.get("qrcode") or data.get("pix_qrcode") or data.get("pixCopiaECola"),
            "expire_at": data.get("expire_at") or billet.get("expire_at"),
            "raw": result,
        }


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return response.text


def _limit_message(value: str | None, limit: int = 400) -> str:
    text = (value or "").strip()
    return text[:limit]


def _format_billet_message(value: str | None) -> str:
    """Efí aceita ate 4 linhas com 100 caracteres por linha no boleto."""
    text = " ".join((value or "").split())
    if not text:
        return ""
    lines = [text[index:index + 100] for index in range(0, min(len(text), 400), 100)]
    return "\n".join(lines[:4])


def _required_text(value: str | None, field: str) -> str:
    text = (value or "").strip()
    if not text:
        raise EfiAPIError(f"Campo obrigatorio ausente para Efí: {field}")
    return text


efi_service = EfiAPIService()
