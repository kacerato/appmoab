#!/bin/bash
set -e

# ── Cria certificados a partir de env vars (Railway não suporta upload de arquivos) ──
if [ -n "$INTER_CERT_CONTENT" ] && [ ! -f /app/certs/inter_cert.crt ]; then
  echo "$INTER_CERT_CONTENT" > /app/certs/inter_cert.crt
  echo "✅ Certificado Inter criado a partir de INTER_CERT_CONTENT"
fi

if [ -n "$INTER_KEY_CONTENT" ] && [ ! -f /app/certs/inter_key.key ]; then
  echo "$INTER_KEY_CONTENT" > /app/certs/inter_key.key
  echo "✅ Chave Inter criada a partir de INTER_KEY_CONTENT"
fi

# ── Roda migrações automaticamente ──
echo "🔄 Executando migrações..."
python -m alembic upgrade head 2>/dev/null || echo "⚠️  Migrações falharam (tabelas podem já existir)"

# ── Seed de dados iniciais ──
echo "🌱 Executando seed..."
python -m app.seed 2>/dev/null || echo "⚠️  Seed falhou (dados já existem)"

# ── Inicia o servidor ──
echo "🚀 Iniciando AquaMoab na porta ${PORT}..."
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" --workers 2
