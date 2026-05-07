# AquaMoab — Sistema de Gestão de Distribuição de Água

Sistema completo para gestão de clientes, leitura de hidrômetros via OCR (Kimi K2.6), faturamento automático e geração de boletos via Banco Inter V3.

## Arquitetura

```
appmoab/
├── backend/         FastAPI (Python) — BFF unificado
├── frontend/        Next.js 16 — Painel administrativo
├── mobile/          Expo/React Native — App do colaborador
└── docker-compose.yml
```

## Stack

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy (async), Pydantic |
| Banco | PostgreSQL (Neon Serverless) |
| Frontend | Next.js 16, TypeScript, CSS vanilla |
| Mobile | Expo SDK 54, React Native, TypeScript |
| Pagamentos | Banco Inter Cobrança V3 (mTLS) |
| OCR | Kimi K2.6 Vision (Moonshot AI) |
| Filas | Celery + Redis |
| Notificações | WhatsApp Cloud API (preparado) |

## Setup Rápido

### 1. Backend
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate  # Windows
pip install -r requirements.txt

# Configure o .env (copie de .env.example)
# Preencha DATABASE_URL com sua connection string do Neon

python -m app.seed           # Cria tabelas + admin + tarifas
uvicorn app.main:app --reload  # http://localhost:8000/docs
```

### 2. Frontend
```bash
cd frontend
npm install
npm run dev  # http://localhost:3000
```

### 3. Mobile
```bash
cd mobile
npm install
npx expo start  # Escanear QR com Expo Go
```

### 4. Docker (produção)
```bash
docker-compose up -d
```

## Credenciais Padrão
- **Email:** admin@aquamoab.com
- **Senha:** admin123

## Configuração de Produção

### Variáveis obrigatórias no `.env`:
| Variável | Descrição |
|---|---|
| `DATABASE_URL` | Connection string Neon (postgresql+asyncpg://...) |
| `SECRET_KEY` | Chave JWT (gerar com `openssl rand -hex 32`) |
| `INTER_CLIENT_ID` | Client ID do Banco Inter |
| `INTER_CLIENT_SECRET` | Client Secret do Banco Inter |
| `INTER_CERT_PATH` | Caminho do certificado .crt |
| `INTER_KEY_PATH` | Caminho da chave .key |
| `KIMI_API_KEY` | API Key do Moonshot AI |
| `REDIS_URL` | URL do Redis (para Celery) |

### Deploy:
- **Frontend:** Vercel (`cd frontend && npx vercel`)
- **Backend:** Render / Railway (Docker)
- **Mobile:** EAS Build (`npx eas build`)

## Fluxo Principal

```
Colaborador (App)          Admin (Painel)           Sistema
─────────────────          ──────────────           ───────
1. Login                   
2. Seleciona cliente       
3. Tira foto hidrômetro
4. OCR extrai leitura ───→ 
5. Confirma valor    ────→ 6. Visualiza na fila
                           7. Aprova leitura ──────→ 8. Calcula fatura
                                                     9. Gera boleto Inter
                                                    10. (WhatsApp) Envia
```

## Licença
Proprietary — Todos os direitos reservados.
