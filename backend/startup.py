"""
AquaMoab — Script de startup para produção (Railway/Docker).

Roda seed e inicia uvicorn.
"""

import os
import sys
import subprocess


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
    run_seed()
    start_server()
