'use client';

import { useEffect, useState, use } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { useAppFeedback } from '@/components/AppFeedbackProvider';
import { useAuth } from '@/lib/auth';
import { fileToDataUrl } from '@/lib/file-base64';
import { ArrowLeft, Download, Copy, Ban, Loader2, MessageCircleMore, CheckCircle2, RotateCcw, Calculator, BellRing, Pencil, Upload, FileCheck2 } from 'lucide-react';

interface InvoiceDocument {
  id: string;
  document_type: string;
  source: string;
  original_name: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  notes: string | null;
  created_at: string;
}

interface Invoice {
  id: string;
  customer_id: string;
  customer_name: string;
  customer_cpf_cnpj: string;
  reading_id: string | null;
  consumption_m3: number;
  tariff_rate: number;
  amount: number;
  original_amount: number | null;
  custom_adjustment_amount: number;
  late_fee_amount: number;
  interest_amount: number;
  days_overdue_charged: number;
  adjustment_reason: string | null;
  charge_type: string;
  reference_month: string;
  due_date: string;
  paid_date: string | null;
  status: string;
  display_status: string | null;
  display_status_label: string | null;
  days_until_due: number | null;
  payment_provider: string | null;
  payment_due_date: string | null;
  efi_charge_id: string | null;
  efi_status: string | null;
  efi_barcode: string | null;
  efi_payment_url: string | null;
  efi_pdf_url: string | null;
  efi_pix_qrcode: string | null;
  overdue_charges_allowed: boolean;
  overdue_charge_blocked_reason: string | null;
  has_pdf: boolean;
  document_count: number;
  documents: InvoiceDocument[];
  created_at: string;
}

interface InvoiceEvent {
  id: string;
  event_type: string;
  previous_status: string | null;
  new_status: string | null;
  reason: string | null;
  payload: Record<string, unknown> | null;
  created_at: string;
}

function fmt(v: number) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v);
}

function formatDateOnly(value: string | null | undefined) {
  return value ? new Date(`${value}T00:00:00`).toLocaleDateString('pt-BR') : null;
}

export default function InvoiceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { confirm, notify, prompt } = useAppFeedback();
  const { isAdmin } = useAuth();
  const [inv, setInv] = useState<Invoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [whatsAppFeedback, setWhatsAppFeedback] = useState<string | null>(null);
  const [events, setEvents] = useState<InvoiceEvent[]>([]);
  const [documents, setDocuments] = useState<InvoiceDocument[]>([]);
  const [receiptFile, setReceiptFile] = useState<File | null>(null);

  useEffect(() => {
    Promise.all([
      api.get<Invoice>(`/invoices/${id}`, { skipCache: true }),
      api.get<InvoiceEvent[]>(`/invoices/${id}/events`, { skipCache: true }).catch(() => []),
    ])
      .then(([invoice, invoiceEvents]) => {
        setInv(invoice);
        setDocuments(invoice.documents || []);
        setEvents(invoiceEvents);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  const downloadPdf = async () => {
    const token = localStorage.getItem('token');
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api'}/invoices/${id}/pdf`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) {
        notify('PDF ainda indisponível', 'A Efí ainda não disponibilizou o PDF desta cobrança. Tente novamente em alguns instantes.', 'warning');
        return;
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `boleto_${id.slice(0, 8)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      notify('Falha ao baixar PDF', 'Erro de conexão ao tentar baixar o PDF.', 'error');
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    notify('Copiado', 'O conteúdo foi enviado para sua área de transferência.', 'success');
  };

  const cancelInvoice = async () => {
    const confirmed = await confirm('Cancelar fatura', 'Deseja realmente cancelar esta fatura?', {
      confirmLabel: 'Cancelar fatura',
    });
    if (!confirmed) return;

    try {
      const updated = await api.post<Invoice>(`/invoices/${id}/cancel`);
      setInv(updated);
      await reloadEvents();
      notify('Fatura cancelada', 'A cobrança foi cancelada e a fatura não poderá ser enviada até ser reaberta.', 'success');
    } catch (e: unknown) {
      notify('Falha ao cancelar fatura', e instanceof Error ? e.message : 'Erro ao cancelar a fatura.', 'error');
    }
  };

  const reloadInvoice = async () => {
    const updated = await api.get<Invoice>(`/invoices/${id}`, { skipCache: true });
    setInv(updated);
    setDocuments(updated.documents || []);
  };

  const downloadDocument = async (invoiceDocument: InvoiceDocument) => {
    const token = localStorage.getItem('token');
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api'}/invoices/${id}/documents/${invoiceDocument.id}/download`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('Documento indisponível');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = invoiceDocument.original_name;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      notify('Falha ao baixar documento', error instanceof Error ? error.message : 'Arquivo indisponível.', 'error');
    }
  };

  const uploadReceipt = async () => {
    if (!receiptFile) return;
    setActionLoading('receipt');
    try {
      const uploaded = await api.post<InvoiceDocument>(`/invoices/${id}/documents`, {
        file_base64: await fileToDataUrl(receiptFile),
        original_name: receiptFile.name,
        mime_type: receiptFile.type,
        document_type: receiptFile.type === 'application/pdf' ? 'payment_confirmation_pdf' : 'payment_receipt_upload',
      });
      setDocuments(current => [uploaded, ...current.filter(item => item.id !== uploaded.id)]);
      setReceiptFile(null);
      await reloadEvents();
      notify('Comprovante armazenado', 'O documento foi incluído no dossiê privado desta fatura.', 'success');
    } catch (error) {
      notify('Falha ao anexar comprovante', error instanceof Error ? error.message : 'Não foi possível enviar o arquivo.', 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const reloadEvents = async () => {
    const updated = await api.get<InvoiceEvent[]>(`/invoices/${id}/events`, { skipCache: true });
    setEvents(updated);
  };

  const editAmount = async () => {
    if (!inv) return;
    const activeInvoice = inv;
    const value = await prompt('Editar valor da fatura', `Valor atual: ${fmt(activeInvoice.amount)}. Informe o novo valor final.`, {
      confirmLabel: 'Salvar valor',
      placeholder: 'Ex: 85.50',
    });
    if (!value) return;
    const parsed = Number(value.replace(',', '.'));
    if (!Number.isFinite(parsed) || parsed < 0) {
      notify('Valor inválido', 'Informe um valor numérico válido.', 'warning');
      return;
    }
    const reason = await prompt('Motivo do ajuste', 'Registre o motivo do desconto ou alteração.', {
      confirmLabel: 'Confirmar',
      placeholder: 'Ex: desconto autorizado',
    });
    setActionLoading('amount');
    try {
      const updated = await api.patch<Invoice>(`/invoices/${id}/amount`, { amount: parsed, reason });
      setInv(updated);
      await reloadEvents();
      notify('Valor atualizado', 'A fatura foi ajustada com sucesso.', 'success');
    } catch (e: unknown) {
      notify('Falha ao ajustar valor', e instanceof Error ? e.message : 'Erro ao editar a fatura.', 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const refreshOverdue = async () => {
    if (!inv) return;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const due = new Date(`${inv.due_date}T00:00:00`);
    if (!inv.overdue_charges_allowed) {
      notify('Atraso sem multa', inv.overdue_charge_blocked_reason || 'Esta fatura não permite cobrança de multa/juros por atraso operacional de leitura.', 'warning');
      return;
    }
    if (due >= today) {
      const confirmed = await confirm('Fatura em dia', 'Você tem certeza? Essa fatura ainda está dentro do prazo e não deve receber multa ou juros.', {
        confirmLabel: 'Recalcular sem multa',
      });
      if (!confirmed) return;
    }
    const value = await prompt('Atualizar atraso', 'Informe a quantidade de dias em atraso. Deixe vazio para usar a data de hoje.', {
      confirmLabel: 'Atualizar',
      placeholder: 'Ex: 12',
    });
    const days = value ? Number(value.replace(',', '.')) : undefined;
    if (days !== undefined && (!Number.isFinite(days) || days < 0)) {
      notify('Dias inválidos', 'Informe uma quantidade válida de dias.', 'warning');
      return;
    }
    setActionLoading('overdue');
    try {
      const updated = await api.post<Invoice>(`/invoices/${id}/refresh-overdue`, { days_overdue: days });
      setInv(updated);
      await reloadEvents();
      notify('Valor atualizado', 'Juros e multa foram recalculados.', 'success');
    } catch (e: unknown) {
      notify('Falha ao atualizar atraso', e instanceof Error ? e.message : 'Erro ao recalcular juros.', 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const markPaid = async () => {
    const confirmed = await confirm('Marcar como paga', 'Confirmar que esta fatura foi paga?', {
      confirmLabel: 'Marcar paga',
    });
    if (!confirmed) return;
    setActionLoading('paid');
    try {
      await api.post(`/invoices/${id}/mark-paid`, {});
      await reloadInvoice();
      await reloadEvents();
      notify('Pagamento registrado', 'A fatura foi marcada como paga.', 'success');
    } catch (e: unknown) {
      notify('Falha ao registrar pagamento', e instanceof Error ? e.message : 'Erro ao marcar como paga.', 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const reopenInvoice = async () => {
    const confirmed = await confirm('Reabrir fatura', 'Deseja reabrir esta fatura para cobrança?', {
      confirmLabel: 'Reabrir',
    });
    if (!confirmed) return;
    const reason = await prompt('Motivo da reabertura', 'Explique por que esta fatura será reaberta. Isso ficará no histórico financeiro.', {
      confirmLabel: 'Registrar motivo',
      placeholder: 'Ex: boleto cancelado por erro de emissão',
    });
    if (!reason || reason.trim().length < 5) {
      notify('Motivo obrigatório', 'Informe um motivo claro para reabrir a fatura.', 'warning');
      return;
    }
    setActionLoading('reopen');
    try {
      const updated = await api.post<Invoice>(`/invoices/${id}/reopen`, { reason: reason.trim() });
      setInv(updated);
      await reloadEvents();
      notify('Fatura reaberta', 'O boleto antigo foi desvinculado. Emita uma nova cobrança Efí antes de enviar ao cliente.', 'success');
    } catch (e: unknown) {
      notify('Falha ao reabrir', e instanceof Error ? e.message : 'Erro ao reabrir fatura.', 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const sendCutNotice = async () => {
    setActionLoading('cut');
    try {
      const result = await api.post<{ detail: string; status: string }>(`/invoices/${id}/cut-notice`);
      notify(result.status === 'sent' ? 'Aviso enviado' : 'Aviso registrado', result.detail || 'Aviso de corte processado.', result.status === 'sent' ? 'success' : 'warning');
    } catch (e: unknown) {
      notify('Falha no aviso de corte', e instanceof Error ? e.message : 'Erro ao enviar aviso.', 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const emitBoleto = async () => {
    setActionLoading('boleto');
    try {
      const updated = await api.post<Invoice>(`/invoices/${id}/emit-boleto`);
      setInv(updated);
      await reloadEvents();
      notify('Cobrança emitida', 'A Efí gerou a cobrança. Use o botão WhatsApp para enviar e registrar a mensagem na conversa.', 'success');
    } catch (e: unknown) {
      notify('Falha ao emitir cobrança', e instanceof Error ? e.message : 'Erro ao emitir cobrança na Efí.', 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const sendWhatsApp = async () => {
    setActionLoading('whatsapp');
    setWhatsAppFeedback(null);
    try {
      const result = await api.post<{ detail: string; status: string }>(`/invoices/${id}/send-whatsapp`);
      setWhatsAppFeedback(result.detail || (result.status === 'sent' ? 'Fatura enviada com sucesso.' : 'Falha ao enviar a fatura.'));
      if (result.status === 'sent') {
        const updated = await api.get<Invoice>(`/invoices/${id}`, { skipCache: true });
        setInv(updated);
      }
      await reloadEvents();
    } catch (e: unknown) {
      setWhatsAppFeedback(e instanceof Error ? e.message : 'Não foi possível encaminhar a fatura pelo WhatsApp.');
      await reloadEvents().catch(() => undefined);
    } finally {
      setActionLoading(null);
    }
  };

  if (loading || !inv) return <div className="loading-page"><div className="spinner" style={{ width: 32, height: 32 }} /></div>;

  return (
    <>
      <Header title={`Fatura ${inv.reference_month}`} subtitle={inv.customer_name} actions={
        <div style={{ display: 'flex', gap: 8 }}>
          {!inv.efi_charge_id && !inv.efi_payment_url && (
            <button className="btn btn-primary btn-sm" onClick={emitBoleto} disabled={actionLoading === 'boleto'}>
              {actionLoading === 'boleto' ? <Loader2 size={14} className="spinner" /> : 'Emitir cobrança Efí'}
            </button>
          )}
          {['pending', 'sent', 'overdue'].includes(inv.status) && (
            <button className="btn btn-secondary btn-sm" onClick={sendWhatsApp} disabled={actionLoading === 'whatsapp'}>
              {actionLoading === 'whatsapp' ? <Loader2 size={14} className="spinner" /> : <MessageCircleMore size={14} />} WhatsApp
            </button>
          )}
          {inv.status !== 'paid' && (
            <button className="btn btn-secondary btn-sm" onClick={editAmount} disabled={actionLoading === 'amount'}>
              {actionLoading === 'amount' ? <Loader2 size={14} className="spinner" /> : <Pencil size={14} />} Valor
            </button>
          )}
          {['pending', 'sent', 'overdue'].includes(inv.status) && inv.overdue_charges_allowed && new Date(`${inv.due_date}T00:00:00`) < new Date(new Date().toDateString()) && (
            <button className="btn btn-secondary btn-sm" onClick={refreshOverdue} disabled={actionLoading === 'overdue'}>
              {actionLoading === 'overdue' ? <Loader2 size={14} className="spinner" /> : <Calculator size={14} />} Atualizar atraso
            </button>
          )}
          {['pending', 'sent', 'overdue'].includes(inv.status) && (
            <button className="btn btn-secondary btn-sm" onClick={sendCutNotice} disabled={actionLoading === 'cut'}>
              {actionLoading === 'cut' ? <Loader2 size={14} className="spinner" /> : <BellRing size={14} />} Aviso corte
            </button>
          )}
          {inv.status !== 'paid' && (
            <button className="btn btn-primary btn-sm" onClick={markPaid} disabled={actionLoading === 'paid'}>
              {actionLoading === 'paid' ? <Loader2 size={14} className="spinner" /> : <CheckCircle2 size={14} />} Pago
            </button>
          )}
          {['cancelled', 'paid'].includes(inv.status) && (
            <button className="btn btn-secondary btn-sm" onClick={reopenInvoice} disabled={actionLoading === 'reopen'}>
              {actionLoading === 'reopen' ? <Loader2 size={14} className="spinner" /> : <RotateCcw size={14} />} Reabrir
            </button>
          )}
          {(inv.has_pdf || inv.efi_pdf_url) && (
            <button className="btn btn-secondary btn-sm" onClick={downloadPdf}><Download size={14} /> PDF</button>
          )}
          {['pending', 'sent'].includes(inv.status) && <button className="btn btn-danger btn-sm" onClick={cancelInvoice}><Ban size={14} /> Cancelar</button>}
        </div>
      } />

      <button className="btn btn-ghost btn-sm" onClick={() => router.push('/faturas')} style={{ marginBottom: 20 }}>
        <ArrowLeft size={14} /> Voltar
      </button>

      {whatsAppFeedback && (
        <div className="card" style={{ marginBottom: 16, padding: 14, borderColor: 'var(--border-hover)' }}>
          <strong style={{ display: 'block', marginBottom: 4 }}>WhatsApp</strong>
          <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{whatsAppFeedback}</span>
        </div>
      )}

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <div className="kpi-card green">
          <div className="kpi-label">Valor</div>
          <div className="kpi-value" style={{ fontSize: 22, color: 'var(--success)' }}>{fmt(inv.amount)}</div>
        </div>
        <div className="kpi-card cyan">
          <div className="kpi-label">Consumo</div>
          <div className="kpi-value" style={{ fontSize: 22 }}>{inv.consumption_m3.toFixed(2)} m³</div>
        </div>
        <div className="kpi-card blue">
          <div className="kpi-label">Vencimento</div>
          <div style={{ fontWeight: 700, fontSize: 15 }}>{formatDateOnly(inv.due_date)}</div>
        </div>
        <div className="kpi-card orange">
          <div className="kpi-label">Status</div>
          <span className={`badge ${inv.display_status || inv.status}`}>{inv.display_status_label || statusLabel(inv.status)}</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="card">
          <div className="card-header"><span className="card-title">Dados da Efí</span></div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, fontSize: 13 }}>
            <Field label="ID da cobrança" value={inv.efi_charge_id} />
            <Field label="Status Efí" value={inv.efi_status} />
            <Field label="Vencimento na Efí" value={formatDateOnly(inv.payment_due_date)} />
            {inv.efi_payment_url && (
              <div>
                <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 4 }}>Link de pagamento</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <code style={{ fontSize: 12, color: 'var(--text-primary)', flex: 1, wordBreak: 'break-all', background: 'var(--navy-900)', padding: '6px 10px', borderRadius: 'var(--radius-sm)' }}>
                    {inv.efi_payment_url}
                  </code>
                  <button className="btn btn-ghost btn-sm btn-icon" onClick={() => copyToClipboard(inv.efi_payment_url!)}>
                    <Copy size={13} />
                  </button>
                </div>
              </div>
            )}
            {inv.efi_barcode && (
              <div>
                <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 4 }}>Linha Digitável</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <code style={{ fontSize: 12, color: 'var(--text-primary)', flex: 1, wordBreak: 'break-all', background: 'var(--navy-900)', padding: '6px 10px', borderRadius: 'var(--radius-sm)' }}>
                    {inv.efi_barcode}
                  </code>
                  <button className="btn btn-ghost btn-sm btn-icon" onClick={() => copyToClipboard(inv.efi_barcode!)}>
                    <Copy size={13} />
                  </button>
                </div>
              </div>
            )}
            {inv.efi_pix_qrcode && (
              <div>
                <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 4 }}>Pix Copia e Cola</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <code style={{ fontSize: 11, color: 'var(--text-secondary)', flex: 1, wordBreak: 'break-all', background: 'var(--navy-900)', padding: '6px 10px', borderRadius: 'var(--radius-sm)', maxHeight: 60, overflow: 'hidden' }}>
                    {inv.efi_pix_qrcode}
                  </code>
                  <button className="btn btn-ghost btn-sm btn-icon" onClick={() => copyToClipboard(inv.efi_pix_qrcode!)}>
                    <Copy size={13} />
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        <div className="card">
          <div className="card-header"><span className="card-title">Informações</span></div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, fontSize: 13 }}>
            <Field label="Cliente" value={inv.customer_name} />
            <Field label="CPF/CNPJ" value={inv.customer_cpf_cnpj} />
            <Field label="Tipo" value={chargeTypeLabel(inv.charge_type)} />
            <Field label="Tarifa" value={`R$ ${inv.tariff_rate.toFixed(2)}/m³`} />
            <Field label="Valor original" value={fmt(inv.original_amount ?? inv.amount)} />
            <Field label="Ajuste manual" value={fmt(inv.custom_adjustment_amount || 0)} />
            <Field label="Multa / juros" value={`${fmt(inv.late_fee_amount || 0)} / ${fmt(inv.interest_amount || 0)} (${inv.days_overdue_charged || 0} dia(s))`} />
            <Field label="Regra de atraso" value={inv.overdue_charges_allowed ? 'Multa e juros permitidos conforme configuração' : inv.overdue_charge_blocked_reason} />
            <Field label="Motivo do ajuste" value={inv.adjustment_reason || null} />
            <Field label="Data Pagamento" value={formatDateOnly(inv.paid_date) || 'Não pago'} />
            <Field label="Emitida em" value={new Date(inv.created_at).toLocaleString('pt-BR')} />
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-header">
          <span className="card-title">Documentos da cobrança</span>
          <span className="badge active">{documents.length} arquivo(s)</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {documents.length === 0 && (
            <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>O dossiê ainda não possui documentos persistidos.</div>
          )}
          {documents.map((document) => (
            <div key={document.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: 12, border: '1px solid var(--border)', borderRadius: 'var(--radius-md)' }}>
              <FileCheck2 size={18} color="var(--accent)" />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 13 }}>{document.original_name}</div>
                <div style={{ color: 'var(--text-muted)', fontSize: 11, marginTop: 3 }}>
                  {documentTypeLabel(document.document_type)} · {(document.size_bytes / 1024).toFixed(1)} KB · {new Date(document.created_at).toLocaleString('pt-BR')}
                </div>
              </div>
              <button className="btn btn-secondary btn-sm" onClick={() => downloadDocument(document)}>
                <Download size={14} /> Baixar
              </button>
            </div>
          ))}
        </div>
        {isAdmin && (
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--border)' }}>
            <input
              type="file"
              accept="application/pdf,image/jpeg,image/png,image/webp"
              onChange={(event) => setReceiptFile(event.target.files?.[0] || null)}
              style={{ flex: 1 }}
            />
            <button className="btn btn-primary btn-sm" onClick={uploadReceipt} disabled={!receiptFile || actionLoading === 'receipt'}>
              {actionLoading === 'receipt' ? <Loader2 size={14} className="spinner" /> : <Upload size={14} />} Anexar comprovante
            </button>
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="card-header"><span className="card-title">Histórico financeiro</span></div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {events.length === 0 && (
            <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>Nenhum evento registrado para esta fatura.</div>
          )}
          {events.map((event) => (
            <div
              key={event.id}
              style={{
                display: 'grid',
                gridTemplateColumns: '170px 1fr',
                gap: 12,
                padding: '10px 0',
                borderTop: '1px solid var(--border)',
                fontSize: 13,
              }}
            >
              <div style={{ color: 'var(--text-muted)' }}>{new Date(event.created_at).toLocaleString('pt-BR')}</div>
              <div>
                <div style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{eventLabel(event.event_type)}</div>
                {(event.previous_status || event.new_status) && (
                  <div style={{ color: 'var(--text-secondary)', marginTop: 3 }}>
                    {event.previous_status ? statusLabel(event.previous_status) : 'Novo'} {'->'} {event.new_status ? statusLabel(event.new_status) : '-'}
                  </div>
                )}
                {event.reason && (
                  <div style={{ color: 'var(--text-muted)', marginTop: 3 }}>{event.reason}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <div>
      <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 2 }}>{label}</div>
      <div style={{ color: 'var(--text-primary)', fontWeight: 500 }}>{value || '—'}</div>
    </div>
  );
}

function statusLabel(s: string) {
  const m: Record<string, string> = { upcoming: 'A vencer', due_today: 'Vence hoje', pending: 'Pendente', sent: 'Enviado', paid: 'Pago', overdue: 'Vencido', cancelled: 'Cancelado' };
  return m[s] || s;
}

function chargeTypeLabel(s: string) {
  const m: Record<string, string> = { water: 'Água', installation: 'Instalação', reconnection: 'Religamento', manual: 'Manual' };
  return m[s] || s;
}

function eventLabel(s: string) {
  const m: Record<string, string> = {
    invoice_created_manual: 'Fatura criada manualmente',
    invoice_created_from_reading: 'Fatura criada pela leitura',
    efi_charge_emitted: 'Cobrança Efí emitida',
    efi_charge_failed: 'Falha ao emitir Efí',
    invoice_cancelled: 'Fatura cancelada',
    invoice_reopened: 'Fatura reaberta',
    invoice_amount_adjusted: 'Valor ajustado',
    invoice_overdue_refreshed: 'Atraso recalculado',
    invoice_marked_paid: 'Pagamento registrado',
    efi_webhook_applied: 'Webhook Efí aplicado',
    whatsapp_invoice_sent: 'WhatsApp enviado',
    whatsapp_invoice_failed: 'Falha no WhatsApp',
  };
  return m[s] || s;
}

function documentTypeLabel(type: string) {
  const labels: Record<string, string> = {
    boleto_pdf: 'Boleto PDF',
    efi_payment_event: 'Confirmação técnica Efí',
    payment_receipt_upload: 'Comprovante enviado',
    payment_confirmation_pdf: 'Comprovante de pagamento',
  };
  return labels[type] || type;
}
