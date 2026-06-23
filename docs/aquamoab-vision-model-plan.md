# Plano de Evolucao do Modelo Visual Aquamoab

## Objetivo

Elevar a leitura local de hidrometros para um fluxo rapido e preciso em tres camadas:

1. Foto unica: aceitar somente quando a evidencia visual e textual concorda.
2. Burst curto: combinar 3 a 7 frames para resolver angulo, reflexo, distancia e rolete em transicao.
3. Modelo treinado local: promover apenas quando passar em gates por cenario, sem depender de GLM/Kimi como cerebro.

## Dataset Minimo

Cada amostra aprovada precisa guardar:

- imagem original;
- crop retificado da janela;
- leitura confirmada com zeros a esquerda;
- marca/modelo quando visivel;
- ambiente: interno, externo, sujo, reflexo, sombra, longe, lado;
- angulo estimado: frontal, leve lado, lado forte, superior/inferior;
- decisao do motor: aceito, revisao, recaptura;
- latencia do caminho usado.

Meta inicial para treinar/promover:

- 300 fotos confirmadas;
- 40 bursts confirmados com 3+ frames;
- 10 exemplos por digito em cada posicao vermelha;
- 30 fotos dificeis: longe, lado, sujeira, reflexo e baixo contraste;
- nenhum hidrometro duplicado no mesmo split de treino e teste.

## Pipeline Local

1. Detectar a janela do contador.
2. Retificar perspectiva.
3. Classificar slots por modelo local.
4. Rodar OCR local como camada secundaria, nunca como verdade absoluta.
5. Fundir slot, OCR e historico anterior.
6. Em burst, usar consenso por prefixo e mediana do ultimo rolete.
7. Bloquear auto preenchimento quando houver baixa confianca, transicao sem historico ou OCR divergente.

## Gates de Promocao

Um modelo candidato so vira `meter-current.yml` quando atingir:

- acuracia exata de foto unica >= 97% no conjunto geral;
- acuracia por digito >= 99.2%;
- erro silencioso de auto preenchimento = 0;
- acuracia exata em burst >= 99%;
- p95 de latencia <= 1200 ms no servidor alvo;
- recall de recaptura/revisao em casos ruins >= 95%;
- regressao zero nas fotos de controle antigas.

## Benchmark Obrigatorio

Rodar:

```powershell
$env:PYTHONPATH='C:\Users\jamaa\projetos\appmoab\backend'
backend\.venv\Scripts\python.exe -m app.scripts.benchmark_meter_vision --case-file C:\caminho\cases.json
```

O JSON de saida deve ser anexado ao treino. Se `silent_errors` for maior que zero, o modelo nao pode ser promovido.

## Proxima Coleta

Para fechar os angulos onde ainda ha perda:

- 5 fotos frontais perto;
- 5 fotos de lado esquerdo;
- 5 fotos de lado direito;
- 5 fotos mais longe;
- 5 fotos com reflexo/contraste ruim;
- 1 burst de 5 frames para cada leitura real.

O app deve preferir burst automatico quando detectar distancia grande ou janela pequena.
