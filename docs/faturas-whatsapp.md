# Faturas: emissão, referência e envio manual

## Significado dos estados

O estado financeiro `sent` é mantido por compatibilidade. Ele é atribuído pela emissão da cobrança Efí, não pelo WhatsApp. A listagem o apresenta como **Emitida** (antiga aba Enviadas). Aprovar uma leitura pode gerar uma fatura, mas uma falha de emissão deixa a fatura pendente. Cobranças avulsas, de instalação ou de taxa fixa também podem existir sem leitura.

O status do WhatsApp vem de `Notification`, canal `whatsapp`, tipo `invoice_generated`, e aparece separadamente. `sent`, `delivered` e `read` significam, respectivamente, envio confirmado pelo provedor, entrega e leitura registradas; não comprovam pagamento.

Sem filtros de mês, todos os meses são consultados. Cada aba mantém o filtro financeiro existente: uma fatura paga ou vencida deixa a aba Emitidas e aparece em Pagas ou Vencidas (e em Todas).

## Datas

- `reference_month`: referência da fatura; não é o mês de pagamento.
- `due_date`: vencimento original da dívida, mantido para as regras financeiras existentes.
- `payment_due_date`: vencimento do boleto emitido/reemitido na Efí.
- `paid_date`: pagamento registrado, não utilizado como filtro de vencimento.

O filtro `due_month=AAAA-MM` usa `coalesce(payment_due_date, due_date)` em um intervalo fechado no início e aberto no primeiro dia do mês seguinte. A tela mostra também o vencimento original quando for diferente. A mensagem de WhatsApp usa o vencimento do boleto. Nenhuma data financeira é alterada por estes filtros.

## Envio manual selecionado

`POST /invoices/send-whatsapp-batch` recebe `invoice_ids` (1 a 100 UUIDs) e exige administrador. O frontend seleciona apenas as linhas da página atual, limpa a seleção ao navegar/trocar filtros e confirma nomes, referências, valores e vencimentos antes de solicitar o envio. Selecionar uma linha não inclui automaticamente outras dívidas do cliente.

O backend elimina IDs repetidos, bloqueia as faturas em ordem estável, valida cada item e reaproveita a fila idempotente existente. Faturas pagas/canceladas, cobranças com pagamento identificado/encerradas, leituras vinculadas não aprovadas, ausência de cobrança e telefones incompletos são recusados com motivo por item. O envio é individual, para o telefone cadastrado do cliente de cada fatura.

`manual_requested` e `requested_by` são gravados no payload da notificação. Essa autorização vale apenas para aquela entrega: não altera `auto_send_invoice_on_approval` nem `notification_flows`. Permite a entrega manual com o fluxo automático desligado, sem ignorar a configuração/conexão global do WhatsApp. O botão individual também utiliza essa autorização.

O lote é persistido antes de iniciar as tarefas em background. A resposta `queued` significa **na fila**, não entregue. As primeiras tentativas usam a tarefa existente, com uma sessão/commit por notificação. Celery Worker e Beat precisam estar ativos para processar os adiamentos duráveis (agenda existente a cada 2 minutos). A listagem atualiza a coluna WhatsApp a cada 15 segundos enquanto houver itens na fila, e oferece atualização manual.

## Proteções e limites

- Uma chave idempotente por fatura/fluxo/canal, preservada entre envio automático e manual.
- Bloqueio da fatura também na primeira inserção, quando ainda não existe notificação para bloquear.
- Entregas confirmadas não são reenviadas por cliques repetidos; o lote não implementa reenvio forçado.
- Limite configurado de envios por minuto e intervalo mínimo por cliente, compartilhados com a fila existente.
- Cliques repetidos não antecipam `next_attempt_at` nem zeram tentativas.
- Revalidação da elegibilidade no momento da entrega (por exemplo, pagamento registrado depois da seleção).
- Pausa de conta restrita também bloqueia novas entregas enfileiradas durante a pausa.
- Auditoria da solicitação manual e dos resultados de envio.

Não há garantia de ausência de bloqueio pelo WhatsApp nem de entrega exatamente uma vez: uma falha entre a aceitação pelo provedor e o commit local pode deixar o resultado incerto. Sem idempotência no provedor, é necessário conferir o histórico antes de qualquer intervenção manual nesses casos. Testes automatizados não enviam mensagens reais.

Não há migração de schema: são utilizados campos existentes e campos adicionais de resposta. Estados financeiros e histórico de cobrança são preservados.
