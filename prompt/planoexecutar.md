# AquaMoab — Sistema de Gestão de Distribuição de Água

Sistema completo para gestão de clientes, leitura de hidrômetros via IA, faturamento automático e cobrança via boleto para distribuição de água de poço artesiano.

## Decisões Confirmadas

| Item                      | Decisão                                            |
| ------------------------- | -------------------------------------------------- |
| **Backend**               | Python + FastAPI (BFF unificado)                   |
| **Banco de Dados**        | Neon (PostgreSQL Serverless)                       |
| **Frontend Web**          | Next.js (Painel Admin) → **Vercel**                |
| **Mobile**                | React Native (App Colaborador)                     |
| **Deploy Backend**        | **Railway**                                        |
| **Tarefas Async**         | Celery + Redis                                     |
| **WhatsApp**              | 🔶 Código preparado, flag `WHATSAPP_ENABLED=false` |
| **Banco Inter**           | API Cobrança V3 com mTLS                           |
| **Kimi K2.6**             | OCR de hidrômetros                                 |
| **Dia vencimento**        | ✅ Configurável por cliente                         |
| **Clientes sem contador** | ✅ Também recebem boleto via Inter (R$100 fixo)     |

---



---

## Fluxo Completo de Faturamento (Atualizado)

### Dois Caminhos de Faturamento

### Ciclo de Vida de uma Fatura

### Fluxo de Notificações (Preparado)

Notification LogWhatsApp APINeon DBCelery WorkerNotification LogWhatsApp APINeon DBCelery WorkerExecuta diariamentealt[WHATSAPP_ENABLED = true][WHATSAPP_ENABLED = false]loop[Para cada fatura]Mesmo fluxo para "vence_hoje" e "atrasado"Busca faturas vencendo em 5 diasEnvia template "vencimento_proximo"message_idRegistra: sentRegistra: queued (aguardando ativação)

no momento vamos usar inter no sandbox

---

## Fórmula de Cálculo da Tarifa ✅

### Tabela de Tarifas (Configurável no Painel)

|Faixa|Tarifa (R$/m³)|
|---|---|
|Até 10 m³|R$ 10,00|
|10 a 15 m³|R$ 11,28|
|15 a 20 m³|R$ 13,04|
|20 a 30 m³|R$ 13,93|
|30 a 40 m³|R$ 14,39|
|40 a 50 m³|R$ 14,58|
|50 a 90 m³|R$ 14,67|
|90 a 150 m³|R$ 14,75|
|Acima de 150 m³|R$ 14,77|

NOTE

Tarifa aplicada sobre **todo** o consumo (não apenas excedente). Taxa mínima: **R$100**. Clientes sem hidrômetro: **R$100 fixo/mês**.

---

## Modelos de Banco de Dados (Neon)

---

## Integrações de API

### Banco Inter V3 ✅

- **Sandbox:** `https://cdpj-sandbox.partners.uatinter.co`
- **Produção:** `https://cdpj.bancointer.com.br`
- Endpoints: `POST /cobranca/v3/cobrancas`, `GET .../pdf`, filtros por situação
- mTLS com certificados já disponíveis no projeto

### Kimi K2.6 Vision ✅

- **URL:** `https://api.moonshot.ai/v1/chat/completions`
- **Modelo:** `kimi-k2.6` — imagem base64 via `image_url` type
- OCR de hidrômetro: extrai código + leitura + confiança

### WhatsApp Cloud API 🔶 (Preparado)

- **URL:** `https://graph.facebook.com/v17.0/{PHONE_ID}/messages`
- Templates prontos no código, flag `WHATSAPP_ENABLED=false`

---

## Frontend — Painel Admin (Next.js + Vercel)

|Rota|Funcionalidade|
|---|---|
|`/login`|Auth JWT|
|`/dashboard`|KPIs: pendentes, valor a receber, inadimplência, leituras, deduções mensais|
|`/customers`|Lista + busca + filtros (ativo/suspenso/desligado, com/sem hidrômetro)|
|`/customers/[id]`|Detalhe completo + timeline + boletos PDF salvos|
|`/customers/new`|Cadastro (com/sem hidrômetro, dia vencimento configurável)|
|`/readings`|Fila aprovação: foto + OCR + GPS + mapa|
|`/invoices`|Todas faturas + filtros + download PDF|
|`/tariffs`|CRUD faixas de tarifa|
|`/settings`|Config APIs + flag WhatsApp + gestão de usuários|

**Design:** Azul marinho (`#0a1628` base, `#3b82f6` accent, `#06b6d4` destaque)

---

## App Mobile — React Native (Colaborador)

**Telas:** Login → Lista Rota (clientes pendentes) → Câmera (overlay) → Resultado OCR → Confirmar → Histórico do dia

**Dados capturados automaticamente:** GPS + timestamp + foto + OCR (código + leitura)

---

## Tarefas Celery

|Task|Schedule|Ação|
|---|---|---|
|`check_payment_status`|Diário 8h|Consulta Inter `?situacao=RECEBIDO` → marca pagas|
|`mark_overdue`|Diário 0h|Faturas vencidas → `overdue`|
|`generate_fixed_invoices`|Mensal dia 1|Gera fatura R$100 + boleto Inter p/ clientes sem hidrômetro|
|`send_reminder_5d`|Diário 9h|🔶 WhatsApp (quando ativar)|
|`send_reminder_due_today`|Diário 8h|🔶 WhatsApp (quando ativar)|
|`send_reminder_overdue`|Diário 10h|🔶 WhatsApp (quando ativar)|

---

## Fases de Implementação

### Fase 1 — Backend Core (Semana 1-2)

-  Estrutura FastAPI + Neon DB + Alembic
-  Auth JWT (admin/collaborator)
-  CRUD Clientes (com/sem hidrômetro, dia vencimento)
-  CRUD Hidrômetros + CRUD Tarifas
-  Serviço Billing (fórmula completa)
-  Serviço Inter API (Python/httpx, mTLS)
-  Serviço Kimi Vision (OCR)
-  Serviço WhatsApp (preparado, flag off)
-  Endpoints: leituras, aprovação, faturas, PDF

### Fase 2 — Painel Admin Next.js (Semana 3-4)

-  Setup Next.js + Design azul marinho
-  Login + Dashboard KPIs
-  CRUD Clientes completo + timeline
-  Fila de aprovação de leituras
-  Faturas + download PDF boleto
-  Config tarifas + settings

### Fase 3 — App Mobile React Native (Semana 5-6)

-  Login + lista rota
-  Câmera com overlay + GPS
-  OCR + validação + confirmação

### Fase 4 — Automações (Semana 7)

-  Celery + Redis
-  Tasks de pagamento + vencimento
-  Tasks geração faturas fixas
-  WhatsApp preparado

---

## Verification Plan

### Testes de Cálculo

10,57 m³ × R$11,28 = R$119,26 ✓

15,02 m³ × R$13,04 = R$195,90 ✓

32,67 m³ × R$14,39 = R$469,98 ✓

5,00 m³ × R$10,00 = R$50,00 → max(100, 50) = R$100,00 ✓

### Fluxo E2E

- Cadastrar cliente → leitura → aprovar → boleto Inter → PDF → download ✓
- Cliente sem hidrômetro → task gera R$100 → boleto Inter ✓