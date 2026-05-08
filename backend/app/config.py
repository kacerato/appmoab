"""
AquaMoab — Configuração centralizada via variáveis de ambiente.

Usa pydantic-settings para validação automática.
Todas as variáveis são carregadas do .env na raiz do backend/.
"""

from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

_env_file = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    """Configurações do sistema AquaMoab."""

    model_config = SettingsConfigDict(
        env_file=str(_env_file) if _env_file.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Aplicação ──────────────────────────────────────────────
    app_name: str = "AquaMoab"
    app_version: str = "1.0.0"
    debug: bool = False
    cors_origins: str = "http://localhost:3000"

    # ── Banco de Dados (Neon) ──────────────────────────────────
    database_url: str

    # ── Redis ──────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── JWT Auth ───────────────────────────────────────────────
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 43200  # 30 dias

    # ── Banco Inter (Cobrança V3) ──────────────────────────────
    inter_client_id: str = ""
    inter_client_secret: str = ""
    inter_cert_path: str = ""
    inter_key_path: str = ""
    inter_sandbox: bool = True
    inter_conta_corrente: str = ""

    # ── WhatsApp / Evolution API ───────────────────────────────
    whatsapp_enabled: bool = False
    evolution_api_url: str = "http://evolution-api:8080"
    evolution_api_key: str = "appmoab-secret-key-123"
    evolution_instance_name: str = "appmoab"
    
    # ── Legacy WhatsApp Cloud API (ignorado se usar Evolution) ─
    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    whatsapp_api_version: str = "v17.0"

    # ── Kimi K2.6 (Moonshot AI) ────────────────────────────────
    kimi_api_key: str = ""

    # ── Upload ─────────────────────────────────────────────────
    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 10

    @property
    def cors_origin_list(self) -> list[str]:
        """Retorna lista de origens CORS permitidas."""
        return [origin.strip() for origin in self.cors_origins.split(",")]

    @property
    def inter_base_url(self) -> str:
        """URL base da API do Inter (sandbox ou produção)."""
        if self.inter_sandbox:
            return "https://cdpj-sandbox.partners.uatinter.co"
        return "https://cdpj.bancointer.com.br"

    @property
    def whatsapp_base_url(self) -> str:
        """URL base da API do WhatsApp."""
        return f"https://graph.facebook.com/{self.whatsapp_api_version}"


@lru_cache
def get_settings() -> Settings:
    """Singleton de configurações — cacheia na primeira chamada."""
    return Settings()
