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

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=settings.efi_cobrancas_base_url,
                timeout=30.0,
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
        self._access_token = data["access_token"]
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
        return response.json() if response.content else {}

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
            "message": _limit_message(mensagem),
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
            "charge_type": "banking_billet",
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
        customer: dict[str, Any] = {
            "email": data["email"] or "sem-email@appmoab.local",
            "phone_number": "".join(c for c in (data.get("telefone") or "") if c.isdigit())[:11] or "0000000000",
            "address": {
                "street": data["endereco"],
                "number": data["numero"] or "S/N",
                "neighborhood": data["bairro"],
                "zipcode": "".join(c for c in data["cep"] if c.isdigit()),
                "city": data["cidade"],
                "complement": "",
                "state": data["uf"],
            },
        }
        if len(digits) == 14:
            customer["juridical_person"] = {"corporate_name": data["nome"], "cnpj": digits}
        else:
            customer["name"] = data["nome"]
            customer["cpf"] = digits
        return customer

    def _normalize_charge_response(self, result: dict) -> dict:
        data = result.get("data") if isinstance(result.get("data"), dict) else result
        payment = data.get("payment") or {}
        billet = payment.get("banking_billet") or {}
        pix = billet.get("pix") or data.get("pix") or {}
        pdf = billet.get("pdf") or data.get("pdf") or {}
        return {
            "charge_id": str(data.get("charge_id") or data.get("id") or ""),
            "status": data.get("status"),
            "barcode": data.get("barcode") or billet.get("barcode"),
            "payment_url": data.get("billet_link") or data.get("link") or billet.get("link"),
            "pdf_url": pdf.get("charge") if isinstance(pdf, dict) else None,
            "pix_qrcode": pix.get("qrcode") if isinstance(pix, dict) else None,
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


efi_service = EfiAPIService()
