app para ter um cadastro de de clientes, com algumas informaçoes. poder anexar boletos ja pago pelo cliente, usando futuramente uma api do banco inter pra gerar o beleto.

cores azul marinho
linguagem python com fastapi, - **BFF (Backend For Frontend) unificado:** Crie um backend único (`api.seudominio.com`) que serve tanto o painel React/Next.js quanto o app mobile, centralizando toda a lógica de negócio.
banco de dados

=====

os boletos vai ser gerado com base no consumo de agua, vai ter um calculo para isso, boleto vai ser gerado e será mandando via api do whatsapp.
o valor vai ser calculado com base nesse calculo

esse agente do api precisa de algumas configuraçoes tambem

como comfimaçao do pagamentgo e etc

saber consumo, info e etc

nesse sistema de pagamento, precisa ter como qualuqer outro dia de pagamento, avisa queme esta no dia de pagamento.

atrasos e etc.

=======

verifique se realmente esses dados sao verdadeiro
### API Efí Pay (Cobranças)

- A API de Cobrança está na versão 3 (a V2 foi descontinuada)[](https://developers.inter.co/references/cobranca-bolepix).
    
- **Principais endpoints:**
    
    - `POST /cobranca/v3/cobrancas` para emitir o título (boleto).
        
    - `GET /cobranca/v3/cobrancas` para filtrar por situação (`VENCIDO`, `RECEBIDO`, `ATRASADO`, etc.)[](https://developers.inter.co/references/cobranca-bolepix).
        
- **Sugestão:** Você pode agendar uma rotina diária no Celery para conferir a situação dos boletos e atualizar automaticamente o status da fatura no seu banco.
    

### 3.2 API do WhatsApp (Cloud API)

- **Migração importante:** Desde julho/2025, a cobrança é por mensagem de template enviada (não mais por janela de conversa).
    
- **Para o seu caso:**
    
    - Crie um template no Meta Business Manager para "Atualização de Fatura" ou "Aviso de Vencimento".
        
    - Use o endpoint `POST /{PHONE_NUMBER_ID}/messages` para enviar o template, preenchendo os placeholders com nome do cliente, valor e código de barras.

## 3. Análise Técnica das APIs (Pontos-Chave)

|API|Funcionalidade Principal|Documentação|
|---|---|---|
|**Inter (Cobrança V3)**|Emissão de boletos com Pix, cobranças parceladas e callbacks de pagamento.|[developers.inter.co](https://developers.inter.co/)|
|**WhatsApp Cloud API**|Envio de templates de mensagem (ex.: cobrança) e notificações de pagamento.|[developers.facebook.com](https://developers.facebook.com/docs/whatsapp/cloud-api)|
|**Kimi K2.6 (Visão)**|Entender imagens, extrair texto (OCR) e interpretar o consumo do hidrômetro.|[platform.moonshot.ai](https://platform.moonshot.ai/)|


api banco inter consulte documentaçao https://developers.inter.co/ 

api do whatsapp pesquise sobre https://developers.facebook.com/documentation/business-messaging/whatsapp/overview

====


basicamnete eu tenho um poço, eu destribuo agua desse poço, ai cada cliente tem o seu hidrometo, todo mes o responsavel vai la e tira foto do hidrometro do cliente pra fazer o calculo de quanto foi usado de agua pela aquela pessoa. 

tem que ter a versao mobile para o colaborador poder registrar o consumo.

ele vai tirar foto do hidrometro, cada hidrometro vai ter um codigo nele, vou usar uma api do kimi https://platform.moonshot.ai/docs/overview modelo kimi 2.6

nessa api do api do kimi ele vai analisar a foto, vai extrair o codigo do hidrometo "como localizar codigo" vai ja associar ao codigo do cliente, vai analisar o hidrometro e extrair o consumo. 

e a foto com essas infromaçoes vai pro painel ja pra esperar aprovaçao, nela atravez do codigo ja vai associar ao cliente todos os dados. vai ficar apenas para analise e aprovaçao para gerar boleto e o boleto sera enviado automaticamente via api do whatsapp



======== em breve
toda foto ela vai coletar localizaçao e data e hora para ficar amostyra no painel tambem
vai ter um painel onde vai mostrar cada foto que ele vai ter que tirar com as informaçoes necessaria como nome do cliente, codigo e localizaçao

versao mobile native para colaborador
**React Native**

- Você pode compartilhar código lógico (ex: chamadas à API do BFF) entre o mobile e o frontend web. É uma escolha sólida para app nativo com um único código.

### 5.1 Versão Mobile Nativa (Colaborador)

O app deve funcionar como um checklist:

1. Abrir o app e fazer login.
    
2. Selecionar o cliente na rota (ou escanear o código do hidrômetro).
    
3. **Câmera nativa:** Abrir a câmera com overlay para guiar o enquadramento do hidrômetro.
    
4. O app captura a foto e automaticamente envia para o BFF (que chama o Kimi).
    
5. O BFF retorna em tempo real o consumo extraído e o código do hidrômetro para o colaborador validar visualmente.
    
6. O colaborador confirma e a leitura vai para a fila de aprovação.

=======

1. **Central de Notificações:** Regras para envio de WhatsApp em 3 estágios:
    
    - **5 dias antes:** "Sua fatura vencerá em breve."
        
    - **Dia do vencimento:** "Sua fatura vence hoje."
        
    - **1 dia de atraso:** "Sua fatura está atrasada. Evite a suspensão."


2. **Fluxo de Aprovação:** No painel, o gestor visualiza a foto, o código extraído e o cliente associado. Com um clique aprova tudo e a API do Inter e WhatsApp são acionadas em sequência.
    
3. **Rastreabilidade na Coleta:** Vincular cada leitura a um colaborador (quem tirou a foto) e ao timestamp exato via GPS.


========
- **Dashboard principal:** Cards com total de faturas pendentes, valor total a receber, inadimplência e índice de leituras do mês.
    
- **CRUD completo:** Clientes, hidrômetros, tarifas e usuários do sistema.
    
- **Log de eventos:** Um timeline para cada cliente mostrando cada comunicação enviada e cada pagamento recebido.


painel de cadastro precisa ser bem completo.
precisa ter ods boletos salvos de cada cliente podendo baixar pdf e etc


===================
**Copie o texto abaixo:**

**Atue como um Arquiteto de Software Sênior e Engenheiro Full-Stack.**

**Objetivo:** Preciso desenvolver um sistema completo de gestão de clientes e faturamento para distribuição de água de um poço artesiano. O sistema englobará um painel administrativo web e um aplicativo mobile para coleta de dados em campo. O design deve adotar o **azul marinho** como cor principal.

**Stack Tecnológico:**

- **Backend (BFF Unificado):** Python com FastAPI (centralizando a lógica de negócio para Web e Mobile).
- **Tarefas Assíncronas:** Celery (para rotinas de checagem de boletos e notificações).
- **Frontend Web (Painel Admin):** React / Next.js.
- **Frontend Mobile (App do Colaborador):** React Native.


**Integrações de API Exigidas:**

1. **API Efí Pay (Cobranças):** Para emissão de boletos/Bolix, cobranças com Pix, callbacks de pagamento e consulta de status.
2. **WhatsApp Cloud API:** Para envio de templates de mensagens automáticas de cobrança.
3. **Kimi K2.6 (Visão Computacional):** Para análise de fotos dos hidrômetros (extração de código de identificação e valor de consumo via processamento de imagem


**Requisitos do Aplicativo Mobile (Colaboradores - React Native):**

- O app deve funcionar como um checklist: login, seleção do cliente na rota ou escaneamento do hidrômetro. tem que ter a lista dos clientes que ele tem que ir la e tirar fot
- Utilizar a câmera nativa com overlay (máscara) para guiar o enquadramento correto do hidrômetro.
- Ao capturar a foto, rastrear automaticamente a **localização via GPS e o timestamp** exato.
- A foto é enviada ao BFF, que chama a API do Kimi. O Kimi extrai o código do hidrômetro e o consumo, retornando em tempo real para o app.
- O colaborador faz a validação visual desses dados na tela. Após confirmação, os dados e a foto vão para a fila de aprovação no painel.


metodo do calculo== 

Vou analisar a planilha em detalhes para entender a estrutura e a lógica de cálculo da água.  
Aqui está a análise completa da planilha e como funciona o cálculo da água:  
  
---  
  
![📊](https://web.telegram.org/a/img-apple-64/1f4ca.png) Estrutura Geral da Planilha  
  
A planilha é organizada em três grandes grupos:  
  
Grupo Descrição  
Clientes Sem Contador Clientes com taxa fixa mensal de R 100 (apenas os "Instalados")  
Clientes Com Contador Dados de leitura mensal (mês anterior → mês atual → consumo → valor)  
Tabela de Validação Tabela de tarifas por faixa de consumo  
  
---  
  
![💧](https://web.telegram.org/a/img-apple-64/1f4a7.png) Como é Feito o Cálculo da Água  
  
1. Clientes SEM Contador (Taxa Fixa)  
Na primeira aba, há uma lista de clientes que não têm hidrômetro. O valor é fixo:  
- Instalados: pagam R 100/mês cada (9 clientes ativos = R 900/mês)  
- Desligados/Cortados: pagam R 0 ou estão como "ok"  
  
2. Clientes COM Contador (Medido)  
Para cada cliente com hidrômetro, o cálculo segue esta lógica:  
  

Contagem = Mês Atual − Mês Anterior
Valor    = max(R$ 100, Contagem × Tarifa)

Ou seja:  
- Existe uma taxa mínima de R 100  
- Se o consumo multiplicado pela tarifa der menos que R 100, cobra-se o mínimo  
- Se der mais que R 100, cobra-se o valor proporcional ao consumo  
  
---  
  
![📋](https://web.telegram.org/a/img-apple-64/1f4cb.png) A Tabela de Tarifas (Aba "Validação")  
  
A tabela de validação define a tarifa por m³ de acordo com o consumo total do mês:  
  
Faixa de Consumo Tarifa (R/m³)  
Até 10 m³ R 10,00  
10 a 15 m³ R 11,28  
15 a 20 m³ R 13,04  
20 a 30 m³ R 13,93  
30 a 40 m³ R 14,39  
40 a 50 m³ R 14,58  
50 a 90 m³ R 14,67  
90 a 150 m³ R 14,75  
Acima de 150 m³ R 14,77  
  
> Observação importante: a tarifa é aplicada sobre TODO o consumo do mês, não apenas sobre o excedente. Quando o cliente muda de faixa (ex: de 15 m³ para 15,1 m³), a tarifa de toda a conta aumenta.  
  
Exemplos Reais da Planilha:  
- Shahira Mak (10,57 m³): 10,57 × 11,28 = R 119,26 ✓  
- Cicero Nelson (15,02 m³): 15,02 × 13,04 = R 195,90 ✓  
- Iraci da Rocha (32,67 m³): 32,67 × 14,39 = R 469,98 ✓  
- Fabio Gusmão (36,21 m³): 36,21 × 14,39 = R 520,91 ✓  
  
---  
  
![🏭](https://web.telegram.org/a/img-apple-64/1f3ed.png) O Caso do POÇO  
  
O POÇO é tratado de forma diferente dos demais clientes:  
- Em meses de consumo zero (12/2025, 01/2026), o valor é fixo (R 3.050 a R 3.130)  
- Em meses com consumo, o cálculo não segue a tabela padrão  
- É provavelmente um poço artesiano com contrato específico ou rateio comunitário  
  
---  
  
![🧮](https://web.telegram.org/a/img-apple-64/1f9ee.png) Totais Mensais e Descontos  
  
No final de cada mês, a planilha soma:  
1. Valor de todos os clientes com contador  
2. + R 900 (clientes sem contador)  
3. − R 3.100 em descontos/despesas fixas:  
   - R 2.000  
   - R 350  
   - R 600  
   - R 150  
  
Exemplo (03/2026):  
- Soma dos clientes: R 4.726,20  
- Sem contador: + R 900  
- Subtotal: R 5.626,20  
- Descontos: − R 3.100  
- Total final: R 2.526,20 (planilha mostra R 1.626,20 — pode haver outro ajuste)  
  
---  
  
![⚠️](https://web.telegram.org/a/img-apple-64/26a0.png) Casos Atípicos Encontrados  
  
Alguns registros fogem do padrão e podem indicar:  
- Taxas extras (multa, religação, juros)  
- Erros de digitação  
- Situações especiais  
  
Exemplos:  
- Maria Benedita (02/2025): consumiu apenas 0,385 m³ e pagou R 137,21  
- Joelma Alice (02/2025): consumiu 7,08 m³ e pagou R 141,47  
- José Cicero Freire (02/2025): consumiu 7,76 m³ e pagou R 116,07  
  
---  
  
![📈](https://web.telegram.org/a/img-apple-64/1f4c8.png) Gráfico da Análise  
  
![Análise da Planilha de Água](sandbox:///mnt/agents/output/analise_agua.png)  
  
O gráfico mostra:  
1. Curva de tarifas: como a tarifa por m³ cresce com o consumo  
2. Dispersão Consumo × Valor: a relação entre consumo e valor da fatura  
3. Evolução do POÇO: comportamento atípico do maior consumidor  
4. Top 10 consumidores: ranking por consumo médio  
  
---  
  
![✅](https://web.telegram.org/a/img-apple-64/2705.png) Resumo da Fórmula  
  

CONSUMO = LEITURA_ATUAL − LEITURA_ANTERIOR

SE CONSUMO ≤ 10 m³:
    TARIFA = R$ 10,00/m³
SENÃO SE CONSUMO ≤ 15 m³:
    TARIFA = R$ 11,28/m³
SENÃO SE CONSUMO ≤ 20 m³:
    TARIFA = R$ 13,04/m³
... (e assim por diante, conforme a tabela)

VALOR_BRUTO = CONSUMO × TARIFA
VALOR_FINAL = MÁXIMO(R$ 100, VALOR_BRUTO)

A planilha é um sistema de tarifa mínima + tarifa variável por faixa de consumo, comum em associações de água comunitárias ou pequenos sistemas de abastecimento.

✦

✦

✦

✦

✦

✦

✦

✦

✦

✦

✦


por enquanto nao vamos usar o whatsapp para encaminha os boletos pq preciso ter um numero, mas ja vamos deixar tudo pronto para tal sistema
