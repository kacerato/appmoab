"""
AquaMoab — Gerenciamento de upload de arquivos (fotos de hidrômetros).
"""

import os
import uuid
import base64
from pathlib import Path

from app.config import get_settings

settings = get_settings()


def ensure_upload_dir() -> Path:
    """Cria o diretório de uploads se não existir."""
    upload_path = Path(settings.upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)
    return upload_path


def save_photo_from_base64(base64_data: str, prefix: str = "reading") -> str:
    """
    Salva uma foto em base64 no disco e retorna o caminho relativo.

    Args:
        base64_data: String base64 da imagem (pode conter ou não o prefixo data:image/...)
        prefix: Prefixo para o nome do arquivo

    Returns:
        Caminho relativo do arquivo salvo
    """
    upload_path = ensure_upload_dir()

    # Remove prefixo data:image/xxx;base64, se presente
    if "," in base64_data:
        header, base64_data = base64_data.split(",", 1)
        # Extrai extensão do header (ex: data:image/jpeg;base64)
        if "image/" in header:
            ext = header.split("image/")[1].split(";")[0]
        else:
            ext = "jpg"
    else:
        ext = "jpg"

    # Gera nome único
    filename = f"{prefix}_{uuid.uuid4().hex}.{ext}"
    filepath = upload_path / filename

    # Decodifica e salva
    image_data = base64.b64decode(base64_data)

    # Verifica tamanho
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    if len(image_data) > max_bytes:
        raise ValueError(f"Arquivo excede o limite de {settings.max_upload_size_mb}MB")

    with open(filepath, "wb") as f:
        f.write(image_data)

    return str(filepath)


def get_photo_base64(filepath: str) -> str | None:
    """Lê uma foto do disco e retorna como base64."""
    if not os.path.exists(filepath):
        return None

    with open(filepath, "rb") as f:
        data = f.read()

    ext = Path(filepath).suffix.lstrip(".")
    return f"data:image/{ext};base64,{base64.b64encode(data).decode('utf-8')}"


def delete_photo(filepath: str) -> bool:
    """Remove um arquivo de foto."""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
            return True
    except OSError:
        pass
    return False
