# AquaMoab Vision V2 — operação, treino e promoção

## O que entrou

O fluxo V2 mantém o reconhecedor de campo atual como baseline e adiciona:

1. quality gate antes do burst;
2. captura com resolução controlada, lanterna explícita e metadados por frame;
3. persistência de todos os frames do burst;
4. probabilidades por posição e estado `stable` ou `n→n+1`;
5. fusão temporal por slot com consenso ordinal de segurança;
6. decodificador mecânico com histórico apenas como evidência secundária;
7. decisões `accepted`, `confirm` e `recapture`;
8. confiança calibrada por artefato versionado;
9. rotulagem de posição/fase transicional no modo Dev;
10. gates que impedem promoção com dataset pequeno ou erro silencioso.

## Migração obrigatória

```powershell
cd C:\Users\jamaa\projetos\appmoab\backend
$env:PYTHONPATH='C:\Users\jamaa\projetos\appmoab\backend'
.\.venv\Scripts\python.exe -m alembic upgrade head
```

A migração `20260721_0004` acrescenta frames, metadados da captura, decisão,
confiança calibrada, versão do decoder e labels por slot. O bootstrap de schema
também contém as mesmas colunas para ambientes que usam a verificação de startup.

## Variáveis

```text
VISION_MODEL_PATH=                 # classificador estável legado/ONNX
VISION_DETECTOR_MODEL_PATH=        # detector ONNX de cantos e limites dos slots
VISION_TRANSITION_MODEL_PATH=      # modelo multi-head de roletes
VISION_CALIBRATION_PATH=           # JSON promovido de calibração
VISION_MODEL_VERSION=meter-field-v3-20260622
VISION_MIN_AUTOFILL_CONFIDENCE=0.985
```

Sem `VISION_CALIBRATION_PATH` promovido, a visão pode sugerir e pedir confirmação,
mas não libera auto-preenchimento. Um JSON com `status: diagnostic` também não
libera o fluxo automático.

## Contrato do modelo de transições

Entrada ONNX:

```text
slot: float32 [batch, 1, 96, 64], escala 0..1
```

Saídas, nesta ordem:

```text
digit_logits             [batch, 10]
transition_state_logits  [batch, 11]  # 0..9 = n→n+1; 10 = estável
phase                    [batch, 1]   # 0..1
visibility               [batch, 1]   # 0..1
```

O detector de visor recebe RGB `640x640` e devolve quatro cantos, confiança e,
opcionalmente, `N+1` limites normalizados dos slots.

## Ciclo de dados

1. Capturar no modo Dev.
2. Digitar a leitura real com zeros à esquerda quando necessário.
3. Marcar a posição que mostra dois números e escolher `Pouco`, `Metade` ou `Muito`.
4. Aprovar a amostra para treino apenas depois de conferir o visor.
5. Exportar o dataset pela rota administrativa:

```text
GET /api/hydrometers/vision-training/export?only_approved=true&limit=2000
```

O split do treinador usa `hydrometer_id`; frames do mesmo equipamento nunca devem
aparecer simultaneamente em treino e validação.

## Treino multi-head

Instalar dependências somente na estação de treino:

```powershell
backend\.venv\Scripts\pip.exe install -r backend\requirements-vision-training.txt
backend\.venv\Scripts\python.exe backend\training\train_transition_model.py `
  --dataset C:\dados\vision-training-v2.json `
  --output C:\modelos\meter-transition-candidate.onnx
```

O treino é recusado com menos de 1.000 slots de treino, 200 de validação ou 100
slots transicionais.

## Benchmark e calibração

```powershell
$env:PYTHONPATH='C:\Users\jamaa\projetos\appmoab\backend'
backend\.venv\Scripts\python.exe -m app.scripts.benchmark_meter_vision `
  --case-file docs\aquamoab-vision-validation-cases.json `
  --output C:\modelos\benchmark-candidate.json

backend\.venv\Scripts\python.exe -m app.scripts.calibrate_meter_vision `
  --benchmark C:\modelos\benchmark-candidate.json `
  --output C:\modelos\meter-calibration-candidate.json
```

A calibração exige por padrão 500 capturas e 100 casos transicionais. O parâmetro
`--allow-small-diagnostic` serve somente para inspecionar a curva; o artefato sai
como `diagnostic` e não autoriza auto-preenchimento.

## Promoção

```powershell
backend\.venv\Scripts\python.exe -m app.scripts.promote_meter_vision `
  --candidate C:\modelos\meter-transition-candidate.onnx `
  --benchmark C:\modelos\benchmark-candidate.json `
  --promote C:\modelos\meter-transition-current.onnx `
  --registry C:\modelos\registry.json
```

Gates padrão:

- 500 casos independentes;
- acurácia exata geral >= 98%;
- acurácia por dígito >= 99,5%;
- acurácia transicional >= 97%;
- burst >= 99%;
- zero erro silencioso;
- p95 <= 1.200 ms.

## Liberação

1. Executar V2 em sombra.
2. Comparar com confirmações humanas por marca, cenário e posição.
3. Habilitar sugestão assistida.
4. Promover calibração.
5. Liberar auto-preenchimento por família de hidrômetro.
6. Nunca habilitar envio automático como consequência do auto-preenchimento.

## Limite atual verificável

O código, o contrato ONNX, o treinador, o dataset V2, a calibração e os gates estão
implementados. O artefato multi-head promovido ainda depende da coleta real mínima.
Até lá, o sistema permanece no modo seguro `confirm`/`recapture` e usa o modelo de
campo anterior como evidência visual.

