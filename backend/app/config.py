"""
AquaMoab - configuracao centralizada via variaveis de ambiente.
"""

import json
from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_env_file = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_env_file) if _env_file.exists() else None,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "AquaMoab"
    app_version: str = "1.0.0"
    debug: bool = False
    cors_origins: str = "http://localhost:3000,https://appmoab.vercel.app"

    database_url: str
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = Field(validation_alias=AliasChoices("JWT_SECRET", "SECRET_KEY"))
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 43200

    inter_client_id: str = ""
    inter_client_secret: str = ""
    inter_cert_path: str = ""
    inter_key_path: str = ""
    inter_sandbox: bool = True
    inter_conta_corrente: str = ""

    whatsapp_enabled: bool = False
    evolution_api_url: str = Field(
        default="http://evolution-api:8080",
        validation_alias=AliasChoices("EVOLUTION_API_URL", "WHATSAPP_SERVICE_URL"),
    )
    evolution_api_key: str = "appmoab-secret-key-123"
    evolution_instance_name: str = "appmoab"

    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    whatsapp_api_version: str = "v17.0"

    kimi_api_key: str = ""

    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 10

    @property
    def cors_origin_list(self) -> list[str]:
        defaults = {
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "https://appmoab.vercel.app",
        }
        raw_value = (self.cors_origins or "").strip()
        parsed: list[str] = []

        if raw_value.startswith("["):
            try:
                loaded = json.loads(raw_value)
                if isinstance(loaded, list):
                    parsed = [str(origin).strip() for origin in loaded if str(origin).strip()]
            except json.JSONDecodeError:
                parsed = []

        if not parsed:
            parsed = [
                origin.strip().strip("\"'")
                for origin in raw_value.split(",")
                if origin.strip().strip("\"'")
            ]

        return sorted(defaults | set(parsed))

    @property
    def inter_base_url(self) -> str:
        if self.inter_sandbox:
            return "https://cdpj-sandbox.partners.uatinter.co"
        return "https://cdpj.bancointer.com.br"

    @property
    def whatsapp_base_url(self) -> str:
        return f"https://graph.facebook.com/{self.whatsapp_api_version}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
