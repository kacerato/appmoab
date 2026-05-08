import base64
import os
import uuid
from pathlib import Path

from app.config import get_settings

settings = get_settings()


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
    upload_path = ensure_upload_dir()
    ext, raw = _parse_data_uri(base64_data, fallback_ext=fallback_ext)
    filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
    filepath = upload_path / filename
    with open(filepath, "wb") as file_handle:
        file_handle.write(raw)
    return str(filepath)


def save_photo_from_base64(base64_data: str, prefix: str = "reading") -> str:
    return save_binary_from_base64(base64_data, prefix=prefix, fallback_ext="jpg")


def build_public_upload_url(filepath: str) -> str:
    return f"/uploads/{Path(filepath).name}"


def get_photo_base64(filepath: str) -> str | None:
    if not os.path.exists(filepath):
        return None

    with open(filepath, "rb") as file_handle:
        data = file_handle.read()

    ext = Path(filepath).suffix.lstrip(".")
    return f"data:image/{ext};base64,{base64.b64encode(data).decode('utf-8')}"


def delete_photo(filepath: str) -> bool:
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
    except OSError:
        pass
    return False
