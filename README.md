# AquaMoab - Sistema de Gestao de Distribuicao de Agua

Sistema completo para gestao de clientes, leitura de hidrometros via OCR (Kimi K2.6), faturamento automatico e geracao de cobrancas via Efi Pay.

## Arquitetura

```text
appmoab/
|-- backend/          FastAPI (Python) - BFF unificado
|-- frontend/         Next.js 16 - Painel administrativo
|-- mobile/           Expo/React Native - App do colaborador
|-- whatsapp-service/ Servico legado local com whatsapp-web.js
`-- docker-compose.yml
```

## Stack

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy async, Pydantic |
| Banco | PostgreSQL (Neon Serverless) |
| Frontend | Next.js 16, TypeScript, CSS |
| Mobile | Expo SDK 54, React Native, TypeScript |
| Pagamentos | Efi Pay API Cobrancas |
| OCR | Kimi K2.6 Vision (Moonshot AI) |
| Filas | Celery + Redis |
| Notificacoes | Evolution API (WhatsApp) |

## Setup rapido

### 1. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# copie backend/.env.example para backend/.env
python -m app.seed
uvicorn app.main:app --reload
```

Backend sobe em `http://localhost:8000` e Swagger em `http://localhost:8000/docs`.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend sobe em `http://localhost:3000`.

### 3. Mobile

```bash
cd mobile
npm install
npx expo start
```

### 4. Docker Compose local

```bash
docker-compose up -d
```

## Variaveis importantes

### Backend

| Variavel | Uso |
|---|---|
| `DATABASE_URL` | Connection string do PostgreSQL |
| `JWT_SECRET` | Segredo JWT principal |
| `SECRET_KEY` | Alias legado aceito pelo backend |
| `REDIS_URL` | Redis usado por Celery |
| `EFI_CLIENT_ID` | Client ID da aplicacao Efi |
| `EFI_CLIENT_SECRET` | Client Secret da aplicacao Efi |
| `EFI_SANDBOX` | `true` para homologacao, `false` para producao |
| `EFI_NOTIFICATION_URL` | URL publica do webhook `/api/webhooks/efi` |
| `EFI_BOLETO_DAYS_TO_WRITE_OFF` | Dias para baixa automatica da cobranca apos vencimento |
| `EFI_CERT_PATH` / `EFI_KEY_PATH` | Certificado cliente em PEM, opcional para Cobranças/Bolix e obrigatorio apenas se o ambiente Efí exigir mTLS |
| `KIMI_API_KEY` | OCR do Kimi |
| `EVOLUTION_API_URL` | URL base da Evolution API |
| `EVOLUTION_API_KEY` | Chave enviada no header `apikey` |
| `EVOLUTION_INSTANCE_NAME` | Nome da instancia usada para envio |

> Variaveis legadas `INTER_CLIENT_ID`, `INTER_CLIENT_SECRET` e `INTER_SANDBOX` ainda sao aceitas pelo backend para compatibilidade, mas novos ambientes devem usar `EFI_*`. Certificados devem ser configurados somente com `EFI_CERT_PATH` e `EFI_KEY_PATH`.

## WhatsApp via Evolution API

- Codigo do backend usa Evolution API em [backend/app/services/whatsapp_api.py](/C:/Users/jamaa/projetos/appmoab/backend/app/services/whatsapp_api.py).
- `docker-compose.yml` usa hostname interno `http://evolution-api:8080`.
- Em Railway, esse hostname local so funciona se service networking criar exatamente esse host. Caso contrario, defina `EVOLUTION_API_URL` com URL privada/interna real do servico Evolution.
- `AUTHENTICATION_API_KEY` configurada na Evolution precisa bater com `EVOLUTION_API_KEY` do backend.
- Log com `Applying migration ...` sozinho nao significa falha. Isso mostra apenas etapa Prisma antes do `start:prod`.

### Suspeitos comuns no Railway

1. Redis ausente ou desconectado.
2. `EVOLUTION_API_URL` apontando para host de Docker local em vez da rede interna do Railway.
3. Healthcheck do servico falhando apos subir.
4. Volume persistente ausente para sessao/estado do WhatsApp.
5. Variaveis obrigatorias faltando ou divergentes entre backend e Evolution.

## Observacao sobre servicos de WhatsApp

- Existe um servico legado em `whatsapp-service/` usando `whatsapp-web.js`.
- Fluxo principal atual do backend aponta para Evolution API, nao para esse servico legado.
- Misturar os dois em producao tende a gerar confusao de sessao, webhook e deploy.

## Deploy

- Frontend: Vercel
- Backend: Railway ou Render via Docker
- Mobile: EAS Build
- Evolution API: servico separado com Redis e persistencia

## Fluxo principal

```text
Colaborador tira foto
-> backend envia para Kimi
-> gestor aprova leitura
-> sistema calcula fatura
-> Efi Pay gera boleto/Bolix
-> backend envia notificacao pelo WhatsApp
```
