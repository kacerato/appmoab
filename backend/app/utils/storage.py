import base64
import os
import uuid
from pathlib import Path
from urllib.parse import quote

from app.config import get_settings

settings = get_settings()


def _r2_enabled() -> bool:
    return (
        settings.storage_backend.lower() == "r2"
        and bool(settings.r2_account_id)
        and bool(settings.r2_access_key_id)
        and bool(settings.r2_secret_access_key)
        and bool(settings.r2_bucket_name)
    )


def _r2_client():
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("boto3 precisa estar instalado para usar Cloudflare R2") from exc

    return boto3.client(
        "s3",
        endpoint_url=f"https://{settings.r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="auto",
    )


def ensure_upload_dir() -> Path:
    upload_path = Path(settings.upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)
    return upload_path


def _parse_data_uri(base64_data: str, fallback_ext: str) -> tuple[str, bytes]:
    ext = fallback_ext
    payload = base64_data

    if "," in base64_data:
        header, payload = base64_data.split(",", 1)
        if "/" in header:
            ext = header.split("/")[-1].split(";")[0].lower()

    raw = base64.b64decode(payload)
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(raw) > max_bytes:
        raise ValueError(f"Arquivo excede o limite de {settings.max_upload_size_mb}MB")

    return ext, raw


def save_binary_from_base64(base64_data: str, prefix: str, fallback_ext: str = "bin") -> str:
    ext, raw = _parse_data_uri(base64_data, fallback_ext=fallback_ext)
    filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"

    if _r2_enabled():
        key = f"uploads/{prefix}/{filename}"
        content_type = f"application/{ext}"
        if ext in {"jpg", "jpeg", "png", "webp"}:
            content_type = f"image/{'jpeg' if ext == 'jpg' else ext}"
        elif ext == "pdf":
            content_type = "application/pdf"
        _r2_client().put_object(
            Bucket=settings.r2_bucket_name,
            Key=key,
            Body=raw,
            ContentType=content_type,
        )
        return f"r2://{settings.r2_bucket_name}/{key}"

    upload_path = ensure_upload_dir()
    filepath = upload_path / filename
    with open(filepath, "wb") as file_handle:
        file_handle.write(raw)
    return str(filepath)


def save_photo_from_base64(base64_data: str, prefix: str = "reading") -> str:
    return save_binary_from_base64(base64_data, prefix=prefix, fallback_ext="jpg")


def build_public_upload_url(filepath: str) -> str:
    if filepath.startswith("r2://"):
        bucket_and_key = filepath.removeprefix("r2://")
        _, _, key = bucket_and_key.partition("/")
        if settings.r2_public_base_url:
            return f"{settings.r2_public_base_url.rstrip('/')}/{quote(key, safe='/')}"
        if _r2_enabled():
            return _r2_client().generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.r2_bucket_name, "Key": key},
                ExpiresIn=settings.r2_presigned_url_expire_seconds,
            )
        return ""

    if settings.public_upload_base_url:
        return f"{settings.public_upload_base_url.rstrip('/')}/{Path(filepath).name}"
    return f"/uploads/{Path(filepath).name}"


def get_photo_base64(filepath: str) -> str | None:
    if filepath.startswith("r2://"):
        bucket_and_key = filepath.removeprefix("r2://")
        bucket, _, key = bucket_and_key.partition("/")
        if not key or not _r2_enabled():
            return None
        obj = _r2_client().get_object(Bucket=bucket, Key=key)
        data = obj["Body"].read()
        ext = Path(key).suffix.lstrip(".")
        return f"data:image/{ext};base64,{base64.b64encode(data).decode('utf-8')}"

    if not os.path.exists(filepath):
        return None

    with open(filepath, "rb") as file_handle:
        data = file_handle.read()

    ext = Path(filepath).suffix.lstrip(".")
    return f"data:image/{ext};base64,{base64.b64encode(data).decode('utf-8')}"


def delete_photo(filepath: str) -> bool:
    if filepath.startswith("r2://"):
        bucket_and_key = filepath.removeprefix("r2://")
        bucket, _, key = bucket_and_key.partition("/")
        if not key or not _r2_enabled():
            return False
        _r2_client().delete_object(Bucket=bucket, Key=key)
        return True

    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
    except OSError:
        pass
    return False
