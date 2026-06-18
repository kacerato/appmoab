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
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout_seconds: int = 30
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = Field(validation_alias=AliasChoices("JWT_SECRET", "SECRET_KEY"))
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 43200

    efi_client_id: str = Field(default="", validation_alias=AliasChoices("EFI_CLIENT_ID", "INTER_CLIENT_ID"))
    efi_client_secret: str = Field(default="", validation_alias=AliasChoices("EFI_CLIENT_SECRET", "INTER_CLIENT_SECRET"))
    efi_sandbox: bool = Field(default=True, validation_alias=AliasChoices("EFI_SANDBOX", "INTER_SANDBOX"))
    efi_notification_url: str = ""
    efi_boleto_days_to_write_off: int = 30
    efi_cert_path: str = ""
    efi_key_path: str = ""
    efi_p12_path: str = ""
    efi_p12_base64: str = ""
    efi_p12_password: str = ""

    whatsapp_enabled: bool = False
    evolution_api_url: str = Field(
        default="http://evolution-api:8080",
        validation_alias=AliasChoices("EVOLUTION_API_URL", "WHATSAPP_SERVICE_URL"),
    )
    evolution_api_key: str = "appmoab-secret-123"
    evolution_instance_name: str = "AquaMoab"

    whatsapp_token: str = ""
    whatsapp_phone_id: str = ""
    whatsapp_api_version: str = "v17.0"

    glm_api_key: str = ""
    vision_enabled: bool = True
    vision_model_path: str = ""
    vision_model_version: str = "meter-opencv-template-v1"
    vision_min_autofill_confidence: float = 0.985
    vision_glm_shadow_enabled: bool = False
    vision_store_debug_artifacts: bool = True

    upload_dir: str = "./uploads"
    max_upload_size_mb: int = 10
    storage_backend: str = "local"
    public_upload_base_url: str = ""
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = ""
    r2_public_base_url: str = ""
    r2_presigned_url_expire_seconds: int = 900

    performance_log_slow_ms: int = 800
    api_private_cache_seconds: int = 20
    rate_limit_enabled: bool = True
    rate_limit_window_seconds: int = 60
    rate_limit_mutation_requests: int = 90
    rate_limit_login_requests: int = 12
    webhook_shared_secret: str = ""

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
    def efi_cobrancas_base_url(self) -> str:
        if self.efi_sandbox:
            return "https://cobrancas-h.api.efipay.com.br"
        return "https://cobrancas.api.efipay.com.br"

    @property
    def whatsapp_base_url(self) -> str:
        return f"https://graph.facebook.com/{self.whatsapp_api_version}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
