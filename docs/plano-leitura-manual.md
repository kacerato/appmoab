# Leitura manual informada pelo cliente

## Objetivo aprovado

Registrar pelo painel uma nova leitura de consumo informada pelo cliente, sem
visita, foto ou GPS obrigatórios. A confirmação calcula pela tarifa vigente,
cria a fatura vinculada, conclui o ciclo e atualiza a base da próxima leitura.
A leitura anterior permanece no histórico. Ajustar base e boleto avulso
continuam com suas funções próprias.

## Implementação

- [x] Botão no hidrômetro dentro do cadastro do cliente.
- [x] Exibir leitura anterior, data, competência e vencimento do ciclo.
- [x] Receber número em m³, data e motivo; foto JPG/PNG/WebP opcional até 8 MB.
- [x] Calcular prévia com a mesma tarifa e cobrança mínima da leitura de campo.
- [x] Confirmar nova leitura oficial com gestor, origem e motivo no histórico.
- [x] Vincular leitura, fatura e ciclo e abrir o ciclo seguinte.
- [x] Retirar o ciclo concluído da fila retornada ao aplicativo.
- [x] Serializar confirmações pelo hidrômetro e exigir o ciclo exibido na tela.
- [x] Impedir lançamento se existe captura pendente, instalação incompleta,
  medidor/cliente inativo, leitura/cobrança ativa no ciclo ou prévia desatualizada.
- [x] Recusar valores inválidos, datas futuras/anteriores e regressão indevida.
  A virada do visor segue a regra existente (base >= 90% da capacidade).
- [x] Destacar consumo acima de 50 m³ e de três vezes o consumo anterior,
  exigindo confirmação explícita de conferência.
- [x] Persistir leitura, base, ciclo e fatura juntos antes de chamar a Efí.
  Falha na emissão mantém a mesma fatura disponível para nova tentativa.
- [x] Reutilizar cancelamento com desfazer leitura para correções: restaura
  base e reabre o ciclo; impede desfazer quando há leitura posterior ou pagamento.

## Contratos

`GET /api/readings/manual-context?hydrometer_id=...` retorna o ciclo pendente.
`POST /api/readings/manual/preview` calcula sem criar leitura/fatura.
`POST /api/readings/manual` confirma com o ciclo, base e valor conferidos.
As três operações exigem administrador. Origem e justificativa usam os campos
de auditoria existentes (`validation_flags`, `review_adjustment_reason`,
`approved_by`, `InvoiceEvent`); não há alteração de esquema necessária.

A data informada pertence ao horário de Fortaleza. O horário de 12h é apenas
uma convenção de armazenamento para uma data sem hora de captura; o instante
real de registro/aprovação permanece em `created_at`/`approved_at`.

## Validação

- [x] Testes HTTP com PostgreSQL local real e Efí simulada: histórico,
  tarifa, próxima base, rota, concorrência, pendências, falha/reemissão,
  cancelamento/substituição, pagamento, leitura posterior e autorização.
- [x] Conferência da tela no navegador local: 120 → 135 m³, consumo de 15 m³,
  R$ 195,60 pela tarifa configurada; confirmação, fatura, histórico e base.
- [x] Build de produção do frontend, TypeScript e ESLint dos arquivos alterados.
- [x] Regressão completa: 174 testes e 4 subtestes aprovados. Inclui 11 casos
  de integração com PostgreSQL real e um contrato de validação sem banco.
- [x] Rollback integral em falha antes da emissão e tentativas simultâneas
  de emissão de boleto serializadas pela mesma fatura.

Para executar os testes de banco, configure
`MANUAL_READING_TEST_DATABASE_URL` com um PostgreSQL local descartável.
O teste recusa servidores remotos e cria/remove um esquema exclusivo por caso.
Nunca emite cobranças reais ou envia mensagens durante esses testes.

## Limites de entrega

A validação de rota comprova a resposta usada pelo aplicativo; não comprova
exibição em um celular físico. A Efí é simulada nos testes. Publicação em
Railway/Vercel e emissão real em produção não fazem parte desta validação local.
