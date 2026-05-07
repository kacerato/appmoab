"""
AquaMoab — Serviço de integração com o Banco Inter (Cobrança V3).

Utiliza mTLS com certificado + chave para autenticação.
Portado do server.js (Node.js) existente para Python/httpx.

Endpoints:
- POST /oauth/v2/token → OAuth2 token
- POST /cobranca/v3/cobrancas → Emitir boleto (assíncrono)
- GET  /cobranca/v3/cobrancas/{id} → Consultar cobrança
- GET  /cobranca/v3/cobrancas/{id}/pdf → Baixar PDF
- GET  /cobranca/v3/cobrancas → Filtrar por situação
"""

import asyncio
import logging
import ssl
from datetime import date
from pathlib import Path

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class InterAPIError(Exception):
    """Erro na comunicação com a API do Banco Inter."""

    def __init__(self, message: str, status_code: int = 0, detail: dict | None = None):
        self.message = message
        self.status_code = status_code
        self.detail = detail or {}
        super().__init__(self.message)


class InterAPIService:
    """
    Cliente para a API de Cobrança V3 do Banco Inter.

    Gerencia o ciclo de vida do token OAuth2 e utiliza mTLS
    para todas as requisições.
    """

    def __init__(self):
        self._access_token: str | None = None
        self._client: httpx.AsyncClient | None = None

    def _create_ssl_context(self) -> ssl.SSLContext:
        """Cria contexto SSL com certificado mTLS."""
        cert_path = Path(settings.inter_cert_path).resolve()
        key_path = Path(settings.inter_key_path).resolve()

        if not cert_path.exists():
            raise InterAPIError(f"Certificado não encontrado: {cert_path}")
        if not key_path.exists():
            raise InterAPIError(f"Chave não encontrada: {key_path}")

        ssl_context = ssl.create_default_context()
        ssl_context.load_cert_chain(
            certfile=str(cert_path),
            keyfile=str(key_path),
        )
        return ssl_context

    async def _get_client(self) -> httpx.AsyncClient:
        """Retorna ou cria o cliente HTTP com mTLS."""
        if self._client is None or self._client.is_closed:
            ssl_context = self._create_ssl_context()
            self._client = httpx.AsyncClient(
                base_url=settings.inter_base_url,
                verify=ssl_context,
                timeout=30.0,
            )
        return self._client

    async def _get_token(self) -> str:
        """Obtém ou reutiliza o token OAuth2."""
        if self._access_token:
            return self._access_token

        client = await self._get_client()

        data = {
            "client_id": settings.inter_client_id,
            "client_secret": settings.inter_client_secret,
            "scope": "boleto-cobranca.read boleto-cobranca.write",
            "grant_type": "client_credentials",
        }

        try:
            response = await client.post(
                "/oauth/v2/token",
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            response.raise_for_status()
            token_data = response.json()
            self._access_token = token_data["access_token"]
            logger.info("Token Inter obtido com sucesso")
            return self._access_token
        except httpx.HTTPStatusError as e:
            logger.error(f"Erro ao obter token Inter: {e.response.text}")
            raise InterAPIError(
                "Falha na autenticação com o Banco Inter",
                status_code=e.response.status_code,
                detail=e.response.json() if e.response.text else {},
            )

    def _auth_headers(self, token: str) -> dict:
        """Headers padrão para requisições autenticadas."""
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "x-conta-corrente": settings.inter_conta_corrente,
        }

    async def emitir_cobranca(
        self,
        valor: float,
        cpf_cnpj: str,
        nome: str,
        email: str,
        endereco: str,
        numero: str,
        bairro: str,
        cidade: str,
        uf: str,
        cep: str,
        data_vencimento: date,
        seu_numero: str,
        mensagem: str = "",
    ) -> dict:
        """
        Emite uma cobrança (boleto) via API V3 do Inter.

        A API V3 é assíncrona: retorna um codigoSolicitacao.
        Fazemos polling para obter os dados completos.

        Returns:
            Dict com: codigoSolicitacao, nossoNumero, linhaDigitavel,
            codigoBarras, pixCopiaECola
        """
        token = await self._get_token()
        client = await self._get_client()

        # Determina tipo de pessoa
        digits = "".join(c for c in cpf_cnpj if c.isdigit())
        tipo_pessoa = "FISICA" if len(digits) == 11 else "JURIDICA"

        payload = {
            "seuNumero": seu_numero,
            "valorNominal": valor,
            "dataVencimento": data_vencimento.isoformat(),
            "numDiasAgenda": 30,
            "pagador": {
                "cpfCnpj": digits,
                "tipoPessoa": tipo_pessoa,
                "nome": nome,
                "endereco": endereco,
                "numero": numero,
                "bairro": bairro,
                "cidade": cidade,
                "uf": uf,
                "cep": "".join(c for c in cep if c.isdigit()),
                "email": email or "",
            },
        }

        if mensagem:
            payload["mensagem"] = {"linha1": mensagem}

        try:
            response = await client.post(
                "/cobranca/v3/cobrancas",
                json=payload,
                headers=self._auth_headers(token),
            )
            response.raise_for_status()
            result = response.json()
            codigo_solicitacao = result.get("codigoSolicitacao")

            logger.info(f"Cobrança emitida: {codigo_solicitacao}")

            if not codigo_solicitacao:
                return result

            # Polling para obter dados completos (API assíncrona)
            boleto_data = await self._poll_cobranca(token, codigo_solicitacao)
            return boleto_data

        except httpx.HTTPStatusError as e:
            logger.error(f"Erro ao emitir cobrança: {e.response.text}")
            self._access_token = None  # Invalida token
            raise InterAPIError(
                "Falha ao emitir boleto no Banco Inter",
                status_code=e.response.status_code,
                detail=e.response.json() if e.response.text else {},
            )

    async def _poll_cobranca(self, token: str, codigo_solicitacao: str, max_attempts: int = 5) -> dict:
        """Faz polling até obter os dados completos da cobrança."""
        client = await self._get_client()

        for attempt in range(max_attempts):
            await asyncio.sleep(1.5 * (attempt + 1))  # Backoff progressivo

            try:
                response = await client.get(
                    f"/cobranca/v3/cobrancas/{codigo_solicitacao}",
                    headers=self._auth_headers(token),
                )
                response.raise_for_status()
                data = response.json()

                # Verifica se os dados do boleto já estão disponíveis
                cobranca = data.get("cobranca", {})
                boleto = data.get("boleto", {})

                if cobranca.get("nossoNumero") or boleto.get("linhaDigitavel"):
                    result = {
                        "codigoSolicitacao": codigo_solicitacao,
                        "nossoNumero": cobranca.get("nossoNumero"),
                        "linhaDigitavel": boleto.get("linhaDigitavel"),
                        "codigoBarras": boleto.get("codigoBarras"),
                        "pixCopiaECola": data.get("pix", {}).get("pixCopiaECola"),
                        "situacao": cobranca.get("situacao"),
                        "raw": data,
                    }
                    logger.info(f"Dados da cobrança obtidos (tentativa {attempt + 1})")
                    return result

            except httpx.HTTPStatusError:
                logger.warning(f"Polling tentativa {attempt + 1}/{max_attempts} falhou")

        # Retorna dados parciais se polling exauriu
        return {
            "codigoSolicitacao": codigo_solicitacao,
            "nossoNumero": None,
            "linhaDigitavel": None,
            "codigoBarras": None,
            "pixCopiaECola": None,
            "situacao": "PROCESSANDO",
            "raw": {},
        }

    async def buscar_pdf(self, codigo_solicitacao: str) -> bytes | None:
        """Busca o PDF do boleto."""
        token = await self._get_token()
        client = await self._get_client()

        try:
            response = await client.get(
                f"/cobranca/v3/cobrancas/{codigo_solicitacao}/pdf",
                headers=self._auth_headers(token),
            )
            response.raise_for_status()
            data = response.json()

            if data.get("pdf"):
                import base64
                return base64.b64decode(data["pdf"])

        except httpx.HTTPStatusError as e:
            logger.warning(f"Erro ao buscar PDF: {e.response.status_code}")

        return None

    async def consultar_situacao(self, situacoes: list[str] | None = None) -> list[dict]:
        """
        Consulta cobranças por situação.

        Args:
            situacoes: Lista de situações (VENCIDO, RECEBIDO, ATRASADO, etc.)

        Returns:
            Lista de cobranças
        """
        token = await self._get_token()
        client = await self._get_client()

        params = {}
        if situacoes:
            params["situacao"] = ",".join(situacoes)

        try:
            response = await client.get(
                "/cobranca/v3/cobrancas",
                params=params,
                headers=self._auth_headers(token),
            )
            response.raise_for_status()
            data = response.json()
            return data.get("cobrancas", [])

        except httpx.HTTPStatusError as e:
            logger.error(f"Erro ao consultar situação: {e.response.text}")
            raise InterAPIError(
                "Falha ao consultar cobranças",
                status_code=e.response.status_code,
            )

    async def close(self):
        """Fecha o cliente HTTP."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# Singleton
inter_service = InterAPIService()
