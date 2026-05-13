'use client';

import { useEffect, useState, use } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { useAppFeedback } from '@/components/AppFeedbackProvider';
import { ArrowLeft, Download, Copy, Ban, Loader2, MessageCircleMore, CheckCircle2, RotateCcw, Calculator, BellRing, Pencil } from 'lucide-react';

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
  inter_codigo_solicitacao: string | null;
  inter_nosso_numero: string | null;
  inter_linha_digitavel: string | null;
  inter_codigo_barras: string | null;
  inter_pix_copia_cola: string | null;
  has_pdf: boolean;
  created_at: string;
}

function fmt(v: number) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v);
}

export default function InvoiceDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { confirm, notify, prompt } = useAppFeedback();
  const [inv, setInv] = useState<Invoice | null>(null);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [whatsAppFeedback, setWhatsAppFeedback] = useState<string | null>(null);

  useEffect(() => {
    api.get<Invoice>(`/invoices/${id}`)
      .then(setInv)
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
        notify('PDF ainda indisponível', 'O Banco Inter ainda está processando o PDF deste boleto. Aguarde alguns segundos e tente novamente.', 'warning');
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
      await api.post(`/invoices/${id}/cancel`);
      const updated = await api.get<Invoice>(`/invoices/${id}`);
      setInv(updated);
      notify('Fatura cancelada', 'O status da fatura foi atualizado.', 'success');
    } catch (e: unknown) {
      notify('Falha ao cancelar fatura', e instanceof Error ? e.message : 'Erro ao cancelar a fatura.', 'error');
    }
  };

  const reloadInvoice = async () => {
    const updated = await api.get<Invoice>(`/invoices/${id}`);
    setInv(updated);
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
      notify('Valor atualizado', 'A fatura foi ajustada com sucesso.', 'success');
    } catch (e: unknown) {
      notify('Falha ao ajustar valor', e instanceof Error ? e.message : 'Erro ao editar a fatura.', 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const refreshOverdue = async () => {
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
    setActionLoading('reopen');
    try {
      await api.post(`/invoices/${id}/reopen`);
      await reloadInvoice();
      notify('Fatura reaberta', 'A fatura voltou para pendente.', 'success');
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
      await api.post(`/invoices/${id}/emit-boleto`);
      const updated = await api.get<Invoice>(`/invoices/${id}`);
      setInv(updated);
      notify('Boleto emitido', 'O Banco Inter gerou a cobrança com sucesso.', 'success');
    } catch (e: unknown) {
      notify('Falha ao emitir boleto', e instanceof Error ? e.message : 'Erro ao emitir boleto no Banco Inter.', 'error');
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
        const updated = await api.get<Invoice>(`/invoices/${id}`);
        setInv(updated);
      }
    } catch (e: unknown) {
      setWhatsAppFeedback(e instanceof Error ? e.message : 'Não foi possível encaminhar a fatura pelo WhatsApp.');
    } finally {
      setActionLoading(null);
    }
  };

  if (loading || !inv) return <div className="loading-page"><div className="spinner" style={{ width: 32, height: 32 }} /></div>;

  return (
    <>
      <Header title={`Fatura ${inv.reference_month}`} subtitle={inv.customer_name} actions={
        <div style={{ display: 'flex', gap: 8 }}>
          {!inv.inter_codigo_solicitacao && (
            <button className="btn btn-primary btn-sm" onClick={emitBoleto} disabled={actionLoading === 'boleto'}>
              {actionLoading === 'boleto' ? <Loader2 size={14} className="spinner" /> : 'Emitir Boleto Inter'}
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
          {['pending', 'sent', 'overdue'].includes(inv.status) && (
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
          {(inv.has_pdf || inv.inter_codigo_solicitacao) && (
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
          <div style={{ fontWeight: 700, fontSize: 15 }}>{new Date(inv.due_date).toLocaleDateString('pt-BR')}</div>
        </div>
        <div className="kpi-card orange">
          <div className="kpi-label">Status</div>
          <span className={`badge ${inv.status}`}>{statusLabel(inv.status)}</span>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="card">
          <div className="card-header"><span className="card-title">Dados do Boleto</span></div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, fontSize: 13 }}>
            <Field label="Nosso Número" value={inv.inter_nosso_numero} />
            <Field label="Cód. Solicitação" value={inv.inter_codigo_solicitacao} />
            {inv.inter_linha_digitavel && (
              <div>
                <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 4 }}>Linha Digitável</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <code style={{ fontSize: 12, color: 'var(--text-primary)', flex: 1, wordBreak: 'break-all', background: 'var(--navy-900)', padding: '6px 10px', borderRadius: 'var(--radius-sm)' }}>
                    {inv.inter_linha_digitavel}
                  </code>
                  <button className="btn btn-ghost btn-sm btn-icon" onClick={() => copyToClipboard(inv.inter_linha_digitavel!)}>
                    <Copy size={13} />
                  </button>
                </div>
              </div>
            )}
            {inv.inter_pix_copia_cola && (
              <div>
                <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 4 }}>Pix Copia e Cola</div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <code style={{ fontSize: 11, color: 'var(--text-secondary)', flex: 1, wordBreak: 'break-all', background: 'var(--navy-900)', padding: '6px 10px', borderRadius: 'var(--radius-sm)', maxHeight: 60, overflow: 'hidden' }}>
                    {inv.inter_pix_copia_cola}
                  </code>
                  <button className="btn btn-ghost btn-sm btn-icon" onClick={() => copyToClipboard(inv.inter_pix_copia_cola!)}>
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
            <Field label="Motivo do ajuste" value={inv.adjustment_reason || null} />
            <Field label="Data Pagamento" value={inv.paid_date ? new Date(inv.paid_date).toLocaleDateString('pt-BR') : 'Não pago'} />
            <Field label="Emitida em" value={new Date(inv.created_at).toLocaleString('pt-BR')} />
          </div>
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
  const m: Record<string, string> = { pending: 'Pendente', sent: 'Enviado', paid: 'Pago', overdue: 'Vencido', cancelled: 'Cancelado' };
  return m[s] || s;
}

function chargeTypeLabel(s: string) {
  const m: Record<string, string> = { water: 'Água', installation: 'Instalação', reconnection: 'Religamento', manual: 'Manual' };
  return m[s] || s;
}
