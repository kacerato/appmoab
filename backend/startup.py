"""
AquaMoab — Script de startup para produção (Railway/Docker).

Cria certificados a partir de env vars, roda seed e inicia uvicorn.
"""

import os
import sys
import asyncio
import subprocess


def write_cert_from_env():
    """Cria arquivos de certificado a partir de variáveis de ambiente."""
    cert_content = os.environ.get("INTER_CERT_CONTENT", "")
    key_content = os.environ.get("INTER_KEY_CONTENT", "")

    os.makedirs("./certs", exist_ok=True)

    if cert_content and not os.path.exists("./certs/inter_cert.crt"):
        with open("./certs/inter_cert.crt", "w") as f:
            f.write(cert_content)
        print("✅ Certificado Inter criado a partir de INTER_CERT_CONTENT")

    if key_content and not os.path.exists("./certs/inter_key.key"):
        with open("./certs/inter_key.key", "w") as f:
            f.write(key_content)
        print("✅ Chave Inter criada a partir de INTER_KEY_CONTENT")


def run_seed():
    """Roda o seed de dados iniciais."""
    print("🌱 Executando seed...")
    try:
        subprocess.run(
            [sys.executable, "-m", "app.seed"],
            check=True,
            timeout=30,
        )
    except Exception as e:
        print(f"⚠️  Seed falhou (dados podem já existir): {e}")


def start_server():
    """Inicia o uvicorn com porta dinâmica."""
    port = os.environ.get("PORT", "8000")
    print(f"🚀 Iniciando AquaMoab na porta {port}...")
    os.execvp(
        sys.executable,
        [
            sys.executable, "-m", "uvicorn",
            "app.main:app",
            "--host", "0.0.0.0",
            "--port", port,
            "--workers", "2",
        ],
    )


if __name__ == "__main__":
    write_cert_from_env()
    run_seed()
    start_server()
