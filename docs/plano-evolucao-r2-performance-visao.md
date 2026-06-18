# Plano de evolução: documentos de cobrança, performance e visão computacional

Data da análise: 18/06/2026

## 1. Decisões executivas

1. **Unificar boleto e comprovantes em um dossiê documental por fatura no R2.** O PostgreSQL deve guardar metadados e relacionamentos; os binários devem ficar no R2 privado.
2. **Atacar primeiro o peso invisível da listagem de faturas.** Hoje a consulta carrega a entidade inteira, incluindo o PDF binário e o JSON bruto da Efí, mesmo quando a lista não mostra esses dados.
3. **Trocar o cache artesanal por cache de dados com stale-while-revalidate e prefetch por intenção.** A tela deve renderizar dados conhecidos imediatamente e atualizar em segundo plano.
4. **Substituir OCR genérico por visão computacional especializada em hidrômetros.** A solução recomendada combina captura em rajada, controle de qualidade, detecção do visor, correção de perspectiva, reconhecimento por posição e um decodificador da mecânica dos roletes.
5. **Transformar correções humanas aprovadas em dataset versionado.** O sistema não deve treinar com a própria previsão sem validação, para não criar um ciclo de autoengano.
6. **GLM/Kimi deixam de ser dependência principal.** Podem permanecer temporariamente como comparadores em modo sombra, sem bloquear o colaborador e sem decidir a leitura.

---

## 2. Diagnóstico do estado atual

### 2.1 Boleto e comprovante

O ambiente local está configurado com `STORAGE_BACKEND=r2` e com as credenciais necessárias presentes. Isso confirma a configuração deste checkout, não a configuração efetivamente publicada no Railway; o deploy deve ser validado separadamente sem expor segredos.

Fluxo atual:

- A Efí devolve `efi_pdf_url`, que é gravada na fatura.
- Quando o backend baixa o PDF, o conteúdo é guardado no PostgreSQL em `invoices.pdf_data` (`LargeBinary`).
- O endpoint de download lê esse binário do banco e o transmite ao navegador.
- Quando um pagamento é confirmado pelo webhook ou pela rotina de consulta, o backend cria um **comprovante técnico em JSON** com dados da Efí e usa o storage compartilhado. Com R2 habilitado, esse JSON vai para o R2 e o caminho `r2://...` fica em `efi_payment_receipt_url`.
- Esse comprovante atual não é necessariamente um PDF bancário nem uma foto enviada pelo pagador; é uma evidência técnica do retorno da Efí.

Conclusão: **o comprovante técnico já usa R2, mas o boleto PDF ainda fica no banco.** Eles ainda não são tratados como documentos irmãos de um mesmo dossiê.

### 2.2 Primeira abertura lenta das telas

Há cinco causas estruturais no código atual:

1. Todas as páginas principais são componentes client-side. A consulta só começa depois que o JavaScript da rota foi baixado, avaliado e montado.
2. O aquecimento de dados só roda em `requestIdleCallback`, podendo esperar até 1,8 segundo. Algumas telas nem entram na lista de aquecimento.
3. A tela de leituras usa `skipCache: true` até na primeira carga e consulta novamente a cada 5 segundos. O prefetch feito pelo layout é descartado por essa tela.
4. A listagem de faturas seleciona a entidade `Invoice` completa. Isso traz `pdf_data` e `efi_raw_response` para a memória mesmo que a resposta da lista não exponha os campos.
5. Endpoints como dashboard e clientes fazem várias consultas sequenciais. Em uma conexão remota com Neon, cada ida e volta acumula latência.

O fato de a segunda visita ser rápida é coerente com chunk, conexão e dados já aquecidos. A meta não deve ser esconder o atraso com spinner; deve ser retirar trabalho do caminho crítico.

### 2.3 Leitura visual atual

O pipeline atual não é uma visão computacional especializada:

- uma única foto é enviada como base64;
- não há detecção do visor, recorte real, correção de perspectiva, detecção de reflexo ou escolha do melhor quadro;
- o GLM-OCR retorna texto e o backend procura sequências numéricas com expressões regulares;
- a confiança é definida como `0.7` quando algum número foi encontrado, e não representa probabilidade calibrada;
- o resultado não preenche automaticamente o campo de leitura no fluxo móvel atual;
- a tabela chamada `kimi_vision_memory` registra previsão e correção, mas nenhum treinamento consome esses registros;
- o colaborador digita o valor final, e esse valor é enviado como verdade operacional.

Portanto, hoje existe **telemetria de acerto/erro**, não um sistema que aprende.

---

## 3. Arquitetura documental no R2

### 3.1 Modelo recomendado

Criar uma tabela `invoice_documents`:

| Campo | Finalidade |
|---|---|
| `id` | UUID do documento |
| `invoice_id` | Fatura à qual o documento pertence |
| `customer_id` | Facilita auditoria e busca |
| `document_type` | `boleto_pdf`, `efi_payment_event`, `payment_receipt_upload`, `payment_confirmation_pdf` |
| `source` | `efi_api`, `efi_webhook`, `customer_upload`, `whatsapp`, `migration` |
| `object_key` | Chave privada no R2, nunca URL pública persistente |
| `original_name` | Nome amigável |
| `mime_type` | Tipo validado pelo backend |
| `size_bytes` | Tamanho para auditoria e limites |
| `sha256` | Integridade, deduplicação e prova de conteúdo |
| `provider_document_id` | ID externo da Efí quando existir |
| `metadata` | JSON pequeno: status, data, versão e dados não sensíveis |
| `created_at` | Data imutável de criação |
| `supersedes_id` | Encadeia uma reemissão sem apagar a anterior |

Chaves sugeridas no bucket:

```text
billing/{customer_id}/{invoice_id}/boleto/{document_id}.pdf
billing/{customer_id}/{invoice_id}/payment-events/{document_id}.json
billing/{customer_id}/{invoice_id}/receipts/{document_id}.{ext}
```

O bucket deve permanecer privado. O backend gera URL assinada curta somente depois de verificar a autorização do usuário. O `R2_PUBLIC_BASE_URL` local já está vazio, o que combina com esse desenho.

### 3.2 Ciclo de vida

1. Ao emitir a cobrança, gravar metadados da Efí e agendar o download do PDF.
2. Baixar o PDF por tarefa idempotente, validar `%PDF`, tamanho e hash, enviar ao R2 e criar `invoice_documents`.
3. No webhook de pagamento, guardar o evento técnico em JSON no R2 e ligá-lo à mesma fatura.
4. Se houver comprovante enviado pelo cliente, aceitar PDF/JPEG/PNG, validar MIME real, calcular hash e criar outro documento no dossiê.
5. A tela da fatura exibe uma seção “Documentos da cobrança”, com boleto, confirmação da Efí e comprovantes enviados.
6. Reemissão cria nova versão. Não sobrescrever silenciosamente o objeto anterior.

### 3.3 Migração sem interrupção

1. Criar a tabela e as rotas novas.
2. Fazer dual-write: novos PDFs vão ao R2; leitura antiga continua como fallback.
3. Executar backfill em lotes pequenos de `pdf_data` para R2, com hash e relatório de sucesso/falha.
4. Comparar quantidade, tamanho e hash; testar download autorizado.
5. Trocar a UI e os envios de WhatsApp para ler o documento do R2.
6. Parar de gravar `pdf_data`.
7. Após janela de segurança e backup, remover `pdf_data` e os caminhos legados. Não manter o banco inchado “por garantia”.

### 3.4 Critérios de aceite

- 100% dos novos boletos têm registro em `invoice_documents` e objeto correspondente no R2.
- O webhook de pagamento cria evento técnico idempotente; webhook repetido não duplica documento.
- Boleto e comprovantes aparecem agrupados na fatura correta.
- Downloads exigem autenticação e usam URL assinada expirada.
- Backfill possui relatório de contagem, hash, falhas e possibilidade de reprocessamento.
- Listagens nunca carregam bytes do documento.

---

## 4. Plano de performance

### 4.1 Medir antes de alterar

Adicionar uma trilha por navegação:

```text
clique na aba
  -> rota visível
  -> início da API
  -> TTFB
  -> tempo SQL
  -> JSON recebido
  -> conteúdo útil renderizado
```

Implementação:

- gerar `X-Request-ID` e `Server-Timing` no backend;
- separar em `Server-Timing`: espera do pool, SQL, serialização e serviços externos;
- no frontend, registrar `performance.mark()` em clique, montagem e dados prontos;
- registrar tamanho da resposta e o `X-Response-Time-Ms` já existente;
- construir relatório p50/p95 por rota, distinguindo visita fria e quente.

Metas iniciais:

- feedback visual da rota: menos de 100 ms;
- página já visitada com dados em cache: menos de 300 ms;
- primeira visita normal: p95 menor que 1,2 s;
- primeira visita realmente fria de infraestrutura: p95 menor que 2,5 s;
- API de lista: p95 menor que 500 ms e resposta inicial menor que 150 KB.

### 4.2 Correções de alto impacto

#### A. Faturas sem blobs na listagem

- Marcar `pdf_data` e `efi_raw_response` como deferred durante a transição.
- Nas listas, selecionar explicitamente apenas as colunas exibidas.
- Calcular `has_pdf` por existência de documento, sem baixar ou carregar o arquivo.
- Depois da migração, remover definitivamente `pdf_data`.

Esta é a primeira correção porque tende a piorar à medida que a base acumula boletos.

#### B. Cache de dados com revalidação

Adotar TanStack Query ou uma camada equivalente com:

- `staleTime` por domínio;
- dados antigos mostrados imediatamente enquanto atualiza;
- deduplicação de requests;
- invalidação por chave afetada, não limpeza de todo o cache em qualquer mutação;
- persistência opcional em sessão para retorno instantâneo após reload;
- cancelamento de requests de busca/filtro que perderam relevância.

Política sugerida:

| Dados | Frescor |
|---|---:|
| leituras pendentes | 5–10 s |
| conversas | 5–10 s enquanto visível |
| dashboard | 30 s |
| clientes e faturas | 60 s |
| hidrômetros | 2 min |
| tarifas/configuração | 5 min |

Na tela de leituras, usar cache na primeira renderização e `skipCache` somente na atualização em segundo plano. Pausar polling quando a aba do navegador não estiver visível e revalidar no foco.

#### C. Prefetch por intenção

- Ao passar o mouse, focar ou tocar no item do menu, prefetch do chunk **e** da consulta exata da tela.
- Logo após autenticação, aquecer imediatamente as três rotas mais prováveis; deixar o restante para ociosidade.
- Manter um mapa único `rota -> chaves de consulta`, evitando divergência entre o prefetch e a URL real da página.
- Incluir hidrômetros, notificações e conversas, hoje ausentes ou incompletos.

#### D. Renderização progressiva

- Criar `loading.tsx` por segmento para resposta imediata.
- Não bloquear Configurações inteira aguardando saúde, deduções, usuário e sistema; cada cartão deve carregar isoladamente.
- Dashboard deve devolver KPIs principais primeiro ou em uma consulta consolidada; problemas operacionais podem revalidar logo depois.

### 4.3 Backend e banco

- Consolidar agregações do dashboard em CTEs ou poucas consultas, evitando muitas viagens sequenciais ao Neon.
- Nas listas, contar e buscar página com queries enxutas. Avaliar `COUNT(*) OVER()` quando o plano for melhor.
- Criar/validar índices compostos a partir de `EXPLAIN (ANALYZE, BUFFERS)`:
  - `invoices(status, due_date)`;
  - `invoices(customer_id, created_at desc)`;
  - `invoices(reference_month, charge_type, status)`;
  - `readings(status, created_at desc)`;
  - `readings(hydrometer_id, captured_at desc)`;
  - `notifications(type, status, created_at desc)`.
- Confirmar se a URL de produção do Neon usa o endpoint pooled quando apropriado.
- Medir se o Railway Serverless está habilitado. Se estiver, separar latência de wake-up da latência da aplicação antes de decidir por serviço sempre ativo.
- Não resolver consulta lenta apenas aumentando workers ou pool; dois workers multiplicam conexões e não corrigem SQL pesado.

### 4.4 Critérios de aceite

- Navegar entre todas as telas duas vezes em teste automatizado e registrar p50/p95.
- A primeira abertura de Faturas não cresce proporcionalmente ao tamanho dos PDFs existentes.
- Nenhuma lista seleciona `pdf_data` ou blobs do R2.
- Leituras mostram cache imediatamente e atualizam sem piscar a página inteira.
- Toda regressão acima de 20% em tamanho ou latência falha no teste de performance do CI.

---

## 5. Motor de visão computacional recomendado

### 5.1 Opções consideradas

| Opção | Vantagem | Limite | Decisão |
|---|---|---|---|
| OpenCV puro | rápido, barato e explicável | regras quebram com marcas, sujeira e rolete parcial | usar no pré-processamento |
| OCR genérico | implantação rápida | lê “texto”; não entende a mecânica do hidrômetro | manter apenas como baseline |
| Modelo multimodal GLM/Kimi | bom para casos variados sem treino local | custo, latência, pouca calibração e comportamento não determinístico | comparador opcional |
| Modelo especializado híbrido | aprende o domínio, mede incerteza e entende posições/transições | exige dataset e disciplina de ML | **arquitetura principal** |

### 5.2 Serviço separado

Criar `vision-service/` em Python, separado da API financeira:

```text
vision-service/
  app/
    api.py
    quality.py
    detector.py
    rectifier.py
    recognizer.py
    transition_decoder.py
    temporal_validator.py
    schemas.py
  models/
  training/
    dataset.py
    augmentations.py
    train_detector.py
    train_recognizer.py
    calibrate.py
    evaluate.py
  tests/
```

Motivos da separação:

- dependências de OpenCV/ONNX não incham nem atrasam o backend financeiro;
- pode escalar CPU/GPU independentemente;
- uma falha do modelo não derruba faturamento;
- permite versionar e fazer rollback do modelo sem redeploy completo do sistema.

Começar em CPU com `opencv-python-headless` e ONNX Runtime. GPU só entra se a medição provar necessidade.

### 5.3 Pipeline de inferência

#### Etapa 1 — captura em rajada

Em vez de uma foto isolada, capturar de 3 a 7 quadros em cerca de 500–800 ms. Para cada quadro, medir no aparelho ou no serviço:

- desfoque;
- exposição baixa/alta;
- reflexo estourado dentro do visor;
- tamanho do visor na imagem;
- inclinação/perspectiva;
- oclusão e corte de borda;
- estabilidade entre quadros.

Escolher o melhor quadro e manter mais dois para consenso. Se todos forem ruins, pedir nova captura com orientação específica: “aproxime”, “reduza o reflexo” ou “alinhe o visor”. Não enviar uma imagem sabidamente inútil para um modelo caro.

#### Etapa 2 — localizar o visor

Treinar detector leve para:

- caixa do hidrômetro;
- região numérica;
- quatro cantos do visor;
- opcionalmente cada posição de dígito.

O cadastro de marca/modelo e quantidade de dígitos vira contexto do modelo, não apenas texto exibido na tela.

#### Etapa 3 — retificar ângulo e lente

- usar os quatro cantos para homografia;
- aplicar correção de perspectiva e rotação;
- normalizar contraste local sem apagar dígitos vermelhos;
- manter versões colorida e tons de cinza;
- tentar pequenas variações de perspectiva/rotação e combinar resultados.

Isso trata fotos laterais de forma geométrica, em vez de esperar que um OCR genérico “imagine” o alinhamento.

#### Etapa 4 — reconhecimento em duas cabeças

Executar dois reconhecedores independentes:

1. **Sequencial:** lê o visor inteiro com CRNN/CTC ou transformer compacto.
2. **Por posição:** divide o visor pelo número cadastrado de casas e classifica cada rolete.

O classificador por posição produz:

- dígito dominante;
- dígito acima e abaixo;
- fase de transição entre 0 e 1;
- visibilidade/oclusão;
- confiança calibrada da posição.

Se as duas cabeças discordarem, a leitura perde confiança e entra na fila humana. O modelo não deve esconder discordância atrás de uma média bonita.

#### Etapa 5 — entender o número “pela metade”

O dígito parcialmente subindo não é ruído aleatório: é um rolete entre `n` e `(n+1) mod 10`. O decodificador deve:

1. detectar as duas metades visíveis;
2. estimar a fase da transição;
3. considerar a direção mecânica do rolete;
4. verificar o carregamento vindo das casas à direita;
5. gerar os poucos números completos compatíveis;
6. ranquear candidatos usando probabilidades visuais e histórico.

Exemplo conceitual:

```text
imagem da posição: metade 4 / metade 5
fase estimada: 0,62
casa à direita: perto de completar a volta
candidatos: 4 ou 5
histórico + regra de transporte: favorece 4 até o cruzamento definido
```

O limiar de cruzamento deve ser aprendido e validado por marca/modelo. Alguns mostradores exibem o próximo número cedo; uma regra universal simples criaria erro sistemático.

#### Etapa 6 — validação temporal e física

Usar como sinais, nunca como desculpa para falsificar a visão:

- leitura anterior;
- número de casas pretas/vermelhas cadastrado;
- consumo máximo plausível por período;
- rollover do mostrador;
- tempo desde a última leitura;
- marca/modelo;
- consenso entre os quadros da rajada.

O motor gera `candidate_readings[]` com razões e probabilidades. Se o melhor candidato violar a física ou não superar claramente o segundo, exigir confirmação humana.

### 5.4 Contrato de saída

```json
{
  "reading": 134.447,
  "confidence": 0.982,
  "auto_fill_allowed": true,
  "model_version": "meter-reader-1.3.0",
  "roi": [120, 310, 920, 540],
  "quality": {
    "blur": 0.06,
    "glare": 0.11,
    "perspective": 0.18
  },
  "digits": [
    {"value": 0, "confidence": 0.999, "transition": false},
    {"value": 4, "next": 5, "phase": 0.62, "confidence": 0.88}
  ],
  "alternatives": [134.447, 135.447],
  "flags": ["transitional_digit"],
  "debug_artifacts": {
    "rectified_object_key": "...",
    "overlay_object_key": "..."
  }
}
```

No aplicativo, “auto_fill_allowed” apenas preenche o campo. Durante a fase inicial, o colaborador continua confirmando antes do envio.

---

## 6. Sistema que se autoalimenta sem se corromper

### 6.1 Dados a guardar

Criar estruturas genéricas, substituindo gradualmente o nome acoplado a Kimi:

- `vision_captures`: imagem original, quadros, melhor quadro, ROI e metadados de captura;
- `vision_inferences`: versão do modelo, previsão, alternativas, confiança, qualidade e latência;
- `vision_labels`: leitura confirmada, dígitos por posição, transições e responsável;
- `vision_model_registry`: versão, dataset, métricas, status champion/challenger e hash do modelo.

Artefatos de imagem ficam no R2; PostgreSQL guarda metadados e chaves. A foto original de `readings` pode ser referenciada, evitando duplicação.

### 6.2 O que vira exemplo de treinamento

Somente:

- leitura confirmada pelo colaborador e aprovada pelo gestor;
- correção explícita de valor/dígito;
- exemplo rotulado na tela de revisão;
- caso sintético gerado por regras controladas e identificado como sintético.

Nunca:

- previsão do próprio modelo sem validação;
- leitura rejeitada sem rótulo correto;
- exemplo de baixa qualidade tratado como verdade;
- duplicatas quase idênticas da mesma rajada no treino e no teste.

### 6.3 Active learning

Priorizar para revisão:

- baixa confiança ou pequena diferença entre primeiro e segundo candidato;
- discordância entre reconhecedor sequencial e por posição;
- dígito transicional;
- nova marca/modelo;
- ângulo, reflexo ou sujeira fora da distribuição comum;
- correção humana;
- anomalia temporal.

Isso faz o esforço humano se concentrar nos exemplos que mais ensinam, em vez de rotular milhares de leituras fáceis.

### 6.4 Treinamento e promoção

1. Versionar dataset e separar treino/validação/teste por **hidrômetro**, não por foto, evitando que quadros quase iguais vazem para o teste.
2. Manter um “golden set” congelado com casos normais, transições, reflexo, sujeira, inclinação e marcas diferentes.
3. Treinar novo candidato apenas quando houver volume mínimo de exemplos novos aprovados ou drift detectado.
4. Calibrar probabilidades e medir erro de calibração, não só acurácia.
5. Rodar challenger em sombra: recebe imagens reais, mas não altera a UI.
6. Promover somente se superar o champion no conjunto global e em cada grupo crítico.
7. Guardar rollback instantâneo para o modelo anterior.

### 6.5 Métricas obrigatórias

- acurácia exata do número completo;
- acurácia por posição;
- acurácia específica em dígitos transicionais;
- precisão do `auto_fill_allowed`;
- cobertura do auto-preenchimento;
- taxa de recaptura por motivo;
- taxa de correção humana;
- falso aceite com alta confiança;
- latência p50/p95 por etapa;
- métricas por marca/modelo, colaborador, aparelho e faixa de ângulo.

Metas de promoção sugeridas:

- precisão do auto-preenchimento de pelo menos 99%;
- nenhum aumento de falso aceite de alta confiança;
- acurácia exata normal de pelo menos 98% no golden set;
- acurácia de transições inicialmente acima do baseline e, com dataset suficiente, meta de 95%;
- inferência p95 abaixo de 1,5 s em CPU no serviço e controle de qualidade local abaixo de 150 ms.

Se a cobertura ficar baixa para preservar 99% de precisão, o sistema continua seguro e aprende com as confirmações. Cobertura deve crescer depois; não se sacrifica a conta correta para parecer “mais automático”.

---

## 7. Fases de execução

### Fase 0 — baseline e amostra real

Entregas:

- instrumentação de navegação/API/SQL;
- relatório das rotas mais lentas;
- exportação segura de exemplos já confirmados;
- taxonomia de falhas visuais;
- golden set inicial, incluindo números parcialmente subindo.

Saída: sabemos quanto demora, onde demora e qual é a acurácia real do pipeline atual.

### Fase 1 — R2 e performance imediata

Entregas:

- `invoice_documents`;
- novos boletos e eventos de pagamento no R2;
- lista de faturas sem blob;
- dual-read/dual-write e backfill;
- cache com revalidação e prefetch por intenção;
- correção da primeira carga de Leituras;
- consultas principais otimizadas e índices medidos.

Saída: documentos organizados, banco mais leve e navegação perceptivelmente rápida antes de introduzir ML pesado.

### Fase 2 — captura inteligente e baseline local

Entregas:

- rajada de quadros;
- quality gate e orientação de recaptura;
- detecção/recorte/retificação do visor;
- benchmark entre PaddleOCR/PP-OCR, reconhecedor sequencial pequeno e pipeline atual;
- telemetria genérica de inferência.

Saída: imagens normalizadas e baseline reproduzível. Nenhum modelo é escolhido por moda; vence o benchmark com as fotos reais do AquaMoab.

### Fase 3 — reconhecedor especializado

Entregas:

- detector do visor/cantos;
- reconhecimento sequencial e por posição;
- classes e regressão de fase transicional;
- validador temporal/mecânico;
- confiança calibrada e alternativas;
- auto-preenchimento ainda com confirmação humana.

Saída: leitura robusta a ângulos e capaz de representar incerteza de roletes parciais.

### Fase 4 — ciclo de aprendizagem

Entregas:

- fila de active learning;
- tela de revisão de ROI e dígitos;
- dataset/model registry;
- treino reprodutível;
- champion/challenger em sombra;
- painel de drift e métricas por segmento.

Saída: cada correção aprovada aumenta a qualidade do próximo modelo sem treinar automaticamente em lixo.

### Fase 5 — inferência no aparelho, se os dados justificarem

Exportar quality gate e/ou modelo leve para ONNX Runtime Mobile. Isso reduz upload e latência, mas requer build nativo personalizado no Expo; não deve ser o primeiro passo. O servidor continua como autoridade e fallback durante a transição.

Saída: experiência rápida mesmo em rede ruim, sem duplicar lógica prematuramente.

---

## 8. Testes e segurança

### Documentos

- upload incompleto, MIME falso, arquivo acima do limite e hash divergente;
- webhook duplicado;
- reemissão e histórico;
- autorização entre usuários;
- URL assinada expirada;
- objeto ausente no R2 e reprocessamento;
- deleção da fatura com política clara de retenção.

### Performance

- teste com centenas/milhares de faturas e PDFs grandes legados;
- primeira e segunda navegação;
- conexão lenta e backend frio;
- busca digitada rapidamente;
- polling em aba oculta;
- mutação invalidando apenas os dados relacionados.

### Visão

- 0°, inclinação lateral e perspectiva forte;
- pouca luz, flash/reflexo e sujeira;
- corte parcial do visor;
- 2 e 3 dígitos vermelhos;
- marcas/modelos distintos;
- rollover;
- cada par transicional `0→1` até `9→0`;
- adversarial simples: etiqueta, QR ou números próximos ao visor;
- comparação entre quadros da rajada;
- teste de regressão por versão de modelo.

---

## 9. Ordem recomendada de implementação

1. Instrumentar latência e tamanho das respostas.
2. Retirar `pdf_data`/`efi_raw_response` das listas.
3. Criar dossiê `invoice_documents` no R2 e migrar PDFs.
4. Corrigir cache, prefetch e polling das telas.
5. Organizar dataset real e golden set.
6. Implementar captura em rajada e quality gate.
7. Implementar detector + retificação.
8. Comparar baselines e treinar reconhecedor especializado.
9. Implementar decodificador de rolete transicional e validador temporal.
10. Implantar active learning e champion/challenger.
11. Só então avaliar inferência on-device completa.

Essa sequência evita dois erros caros: treinar sobre fotos ruins e colocar ML sofisticado em cima de uma aplicação ainda carregando PDFs inteiros para montar uma tabela.

---

## 10. Referências técnicas para a implementação

- OpenCV fornece transformação de perspectiva por quatro pontos e `warpPerspective`, base da retificação geométrica do visor: https://docs.opencv.org/4.x/da/d54/group__imgproc__transform.html
- PaddleOCR possui módulos oficiais de classificação de orientação e correção de imagem; deve entrar como baseline comparável, não como decisão antecipada: https://www.paddleocr.ai/latest/en/version3.x/module_usage/doc_img_orientation_classification.html e https://www.paddleocr.ai/latest/en/version3.x/module_usage/text_image_unwarping.html
- ONNX Runtime Mobile oferece execução em Android/iOS e caminho React Native para levar modelos menores ao aparelho: https://onnxruntime.ai/docs/tutorials/mobile/
- Há literatura específica de reconhecimento de hidrômetros de rolete, confirmando que o problema merece modelo de domínio em vez de OCR textual genérico: https://doi.org/10.1117/1.JEI.31.2.023023
- Trabalho aberto em Scientific Reports trata detecção/recorte do mostrador e reconhecimento como estágios de deep learning: https://www.nature.com/articles/s41598-022-17255-3
- Railway Serverless pode adormecer serviços por inatividade quando habilitado; isso deve ser medido como componente separado da latência fria: https://docs.railway.com/reference/app-sleeping
- Neon oferece endpoint com PgBouncer para pooling; deve-se validar a URL de produção antes de alterar pools do SQLAlchemy: https://neon.com/docs/connect/connection-pooling
