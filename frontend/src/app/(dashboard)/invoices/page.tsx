'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import Header from '@/components/Header';
import { useAppFeedback } from '@/components/AppFeedbackProvider';
import { Download, ChevronLeft, ChevronRight, MessageCircleMore, Loader2 } from 'lucide-react';

interface Invoice {
  id: string;
  customer_id: string;
  customer_name: string;
  customer_cpf_cnpj: string;
  amount: number;
  consumption_m3: number;
  tariff_rate: number;
  due_date: string;
  payment_due_date: string | null;
  paid_date: string;
  status: string;
  display_status: string | null;
  display_status_label: string | null;
  days_until_due: number | null;
  reference_month: string;
  has_pdf: boolean;
  efi_pdf_url: string | null;
  efi_payment_url: string | null;
  whatsapp_status: string | null;
  whatsapp_detail: string | null;
  whatsapp_block_reason: string | null;
}

interface ListRes {
  items: Invoice[];
  total: number;
  page: number;
  per_page: number;
}

interface WhatsAppDispatchResult {
  invoice_id: string;
  status: string;
  reason: string;
  detail: string | null;
}

function fmt(v: number) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v);
}

function formatDateOnly(value: string | null | undefined) {
  return value ? new Date(`${value}T00:00:00`).toLocaleDateString('pt-BR') : '';
}

export default function InvoicesPage() {
  const router = useRouter();
  const { notify, confirm } = useAppFeedback();
  const { isAdmin } = useAuth();
  const [data, setData] = useState<ListRes | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [page, setPage] = useState(1);
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [sendFeedback, setSendFeedback] = useState<Record<string, WhatsAppDispatchResult>>({});
  const [selected, setSelected] = useState<string[]>([]);
  const [sendingBatch, setSendingBatch] = useState(false);
  const [referenceMonth, setReferenceMonth] = useState('');
  const [dueMonth, setDueMonth] = useState('');
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [loadError, setLoadError] = useState('');
  const requestVersion = useRef(0);
  const sendLock = useRef(false);

  const load = useCallback(async (quiet = false) => {
    const version = ++requestVersion.current;
    if (!quiet) setLoading(true);
    try {
      const params = new URLSearchParams({ page: String(page), per_page: '20' });
      if (filter) params.set('status', filter);
      if (referenceMonth) params.set('reference_month', referenceMonth);
      if (dueMonth) params.set('due_month', dueMonth);
      if (search) params.set('search', search);
      const result = await api.get<ListRes>(`/invoices?${params}`, { skipCache: true });
      if (version !== requestVersion.current) return;
      setData(result);
      setLoadError('');
      setSelected(current => current.filter(id => result.items.some(inv => inv.id === id && canSend(inv))));
    } catch (e) {
      if (version === requestVersion.current) {
        setLoadError(e instanceof Error ? e.message : 'Falha ao carregar as faturas.');
        setSelected([]);
      }
    } finally {
      if (version === requestVersion.current) setLoading(false);
    }
  }, [page, filter, referenceMonth, dueMonth, search]);

  useEffect(() => {
    load();
    return () => { requestVersion.current += 1; };
  }, [load]);

  const hasQueued = data?.items.some(inv => inv.whatsapp_status === 'queued');
  useEffect(() => {
    if (!hasQueued) return;
    const timer = window.setInterval(() => { void load(true); }, 15000);
    return () => window.clearInterval(timer);
  }, [hasQueued, load]);

  const downloadPdf = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const token = localStorage.getItem('token');
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api'}/invoices/${id}/pdf`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error('PDF não disponível');
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `boleto_${id.slice(0, 8)}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      notify('Falha ao baixar PDF', err instanceof Error ? err.message : 'Erro ao baixar o PDF.', 'error');
    }
  };

  const sendWhatsApp = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (sendLock.current) return;
    sendLock.current = true;
    setSendingId(id);
    try {
      if (!await confirm('Enviar fatura pelo WhatsApp?', 'Será enviado somente o boleto desta linha, com os mesmos limites de segurança da fila.', { confirmLabel: 'Enviar pelo WhatsApp' })) return;
      const result = await api.post<WhatsAppDispatchResult>(`/invoices/${id}/send-whatsapp`);
      setSendFeedback(current => ({ ...current, [id]: result }));
      await load(true);
    } catch (err: unknown) {
      setSendFeedback(current => ({
        ...current,
        [id]: {
          invoice_id: id,
          status: 'failed',
          reason: 'request_failed',
          detail: err instanceof Error ? err.message : 'Falha ao acionar o envio por WhatsApp.',
        },
      }));
    } finally {
      sendLock.current = false;
      setSendingId(null);
    }
  };

  const sendSelected = async () => {
    if (sendLock.current || !selected.length) return;
    sendLock.current = true;
    setSendingBatch(true);
    const invoices = (data?.items || []).filter(inv => selected.includes(inv.id) && canSend(inv));
    try {
      if (!invoices.length) return;
      const customers = new Set(invoices.map(inv => inv.customer_id)).size;
      const preview = invoices.map(inv => `${inv.customer_name} · ref. ${inv.reference_month} · ${fmt(inv.amount)} · boleto ${formatDateOnly(inv.payment_due_date || inv.due_date)}`).join('; ');
      if (!await confirm(
        `Enviar ${invoices.length} fatura(s) para ${customers} cliente(s)?`,
        `${preview}. Cada cliente recebe apenas os próprios boletos, individualmente. Funciona com o automático desligado, mas exige WhatsApp conectado. A fila respeita pausas e limites; envios adiados continuam depois. Faturas já enviadas não serão reenviadas.`,
        { confirmLabel: 'Confirmar envio pelo WhatsApp' },
      )) return;
      const result = await api.post<{ items: WhatsAppDispatchResult[] }>('/invoices/send-whatsapp-batch', { invoice_ids: invoices.map(inv => inv.id) });
      setSendFeedback(current => ({ ...current, ...Object.fromEntries(result.items.map(item => [item.invoice_id, item])) }));
      const queued = result.items.filter(item => item.status === 'queued').length;
      const skipped = result.items.filter(item => item.reason === 'already_sent').length;
      const failed = result.items.filter(item => item.status === 'failed').length;
      notify('Solicitação processada', `${queued} na fila; ${skipped} já enviada(s); ${failed} não aceita(s). Acompanhe a coluna WhatsApp.`, failed ? 'warning' : 'success');
      setSelected([]);
      await load(true);
    } catch (err) {
      notify('Não foi possível confirmar o lote', `${err instanceof Error ? err.message : 'Erro de comunicação.'} Atualize a lista antes de tentar novamente; a solicitação pode ter sido recebida.`, 'error');
      await load(true);
    } finally {
      sendLock.current = false;
      setSendingBatch(false);
    }
  };

  const eligible = (data?.items || []).filter(canSend);
  const busy = sendingBatch || sendingId !== null;
  const resetSelection = () => { setSelected([]); setSendFeedback({}); setPage(1); };

  const totalPages = data ? Math.ceil(data.total / data.per_page) : 0;

  return (
    <>
      <Header title="Faturas" subtitle={`${data?.total || 0} registros`} />

      <div className="toolbar">
        {[
          { v: '', l: 'Todas' },
          { v: 'upcoming', l: 'A vencer' },
          { v: 'pending', l: 'Pendentes' },
          { v: 'sent', l: 'Emitidas' },
          { v: 'paid', l: 'Pagas' },
          { v: 'overdue', l: 'Vencidas' },
          { v: 'cancelled', l: 'Canceladas' },
        ].map(f => (
          <button key={f.v} disabled={busy} className={`btn ${filter === f.v ? 'btn-primary' : 'btn-secondary'} btn-sm`} onClick={() => { setFilter(f.v); resetSelection(); }}>
            {f.l}
          </button>
        ))}
      </div>

      <p style={{ color: 'var(--text-secondary)', marginBottom: 16 }}>
        Emitidas (antiga “Enviadas”) indica a cobrança emitida, não o envio por WhatsApp nem a aprovação da leitura.
        Sem filtro de mês, aparecem referências de todos os meses, inclusive anteriores. Pagas, vencidas e canceladas ficam nas respectivas abas.
      </p>
      <div className="toolbar" style={{ alignItems: 'end', flexWrap: 'wrap' }}>
        <label>Referência da fatura
          <input className="form-input" aria-label="Referência da fatura" type="month" value={referenceMonth} disabled={busy} onChange={e => { setReferenceMonth(e.target.value); resetSelection(); }} />
        </label>
        <label>Vencimento do boleto
          <input className="form-input" aria-label="Mês de vencimento do boleto" type="month" value={dueMonth} disabled={busy} onChange={e => { setDueMonth(e.target.value); resetSelection(); }} />
        </label>
        <form style={{ display: 'flex', gap: 8, alignItems: 'end', flexWrap: 'wrap' }} onSubmit={e => { e.preventDefault(); setSearch(searchInput.trim()); resetSelection(); }}>
          <label>Cliente<input className="form-input" value={searchInput} disabled={busy} onChange={e => setSearchInput(e.target.value)} placeholder="Nome do cliente" /></label>
          <button className="btn btn-secondary" disabled={busy}>Buscar</button>
        </form>
        <button className="btn btn-ghost" disabled={busy} onClick={() => { setReferenceMonth(''); setDueMonth(''); setSearch(''); setSearchInput(''); resetSelection(); }}>Limpar filtros</button>
        <button className="btn btn-secondary" disabled={busy || loading} onClick={() => { void load(); }}>Atualizar</button>
      </div>
      {loadError && <p role="alert" style={{ color: 'var(--danger)' }}>Falha ao atualizar: {loadError}. Atualize a lista para continuar.</p>}
      {isAdmin && (
        <div className="toolbar" style={{ flexWrap: 'wrap' }}>
          <button className="btn btn-primary" disabled={busy || loading || !!loadError || !selected.length} onClick={sendSelected}>
            {sendingBatch ? <Loader2 size={18} className="spinner" /> : <MessageCircleMore size={18} />} WhatsApp ({selected.length})
          </button>
          <button className="btn btn-ghost" disabled={busy || !selected.length} onClick={() => setSelected([])}>Limpar seleção</button>
          <span style={{ color: 'var(--text-muted)' }}>Seleção somente desta página. Uma fatura por linha; não seleciona outras dívidas do cliente.</span>
        </div>
      )}

      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th>{isAdmin && <label style={{ display: 'grid', placeItems: 'center', minWidth: 44, minHeight: 44 }}><input type="checkbox" aria-label="Selecionar faturas elegíveis desta página" disabled={busy || loading || !!loadError || !eligible.length} checked={eligible.length > 0 && eligible.every(inv => selected.includes(inv.id))} ref={node => { if (node) node.indeterminate = selected.length > 0 && selected.length < eligible.length; }} onChange={e => setSelected(e.target.checked ? eligible.map(inv => inv.id) : [])} /></label>}</th>
              <th>Cliente</th><th>Ref</th><th>Consumo</th><th>Valor</th><th>Vencimento do boleto</th><th>Status da fatura</th><th>WhatsApp</th><th>Ações</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={9}><div className="loading-page" style={{ height: 200 }}><div className="spinner" /></div></td></tr>
            ) : !data?.items.length ? (
              <tr><td colSpan={9}><div className="empty-state"><p>Nenhuma fatura encontrada</p></div></td></tr>
            ) : data.items.map(inv => {
              const feedback = sendFeedback[inv.id];
              const canSendWhatsApp = isAdmin && canSend(inv);

              return (
                <tr key={inv.id} onClick={() => router.push(`/faturas/${inv.id}`)} style={{ cursor: 'pointer' }}>
                  <td onClick={e => e.stopPropagation()}>{isAdmin && <label style={{ display: 'grid', placeItems: 'center', minWidth: 44, minHeight: 44 }} title={inv.whatsapp_block_reason || 'Selecionar esta fatura'}><input type="checkbox" aria-label={`Selecionar ${inv.customer_name}, referência ${inv.reference_month}`} disabled={busy || !!loadError || !canSendWhatsApp} checked={selected.includes(inv.id)} onChange={e => setSelected(current => e.target.checked ? [...current, inv.id] : current.filter(id => id !== inv.id))} /></label>}</td>
                  <td className="cell-primary">
                    {inv.customer_name}
                    {feedback && !['sent', 'delivered', 'read'].includes(inv.whatsapp_status || '') && (
                      <div style={{ fontSize: 11, fontWeight: 500, color: feedback.status === 'sent' ? 'var(--success)' : feedback.status === 'queued' ? 'var(--warning)' : 'var(--danger)', marginTop: 4 }}>
                        {feedback.detail}
                      </div>
                    )}
                  </td>
                  <td>{inv.reference_month}</td>
                  <td>{inv.consumption_m3.toFixed(2)} m³</td>
                  <td style={{ fontWeight: 700 }}>{fmt(inv.amount)}</td>
                  <td>{formatDateOnly(inv.payment_due_date || inv.due_date)}
                    {inv.payment_due_date && inv.payment_due_date !== inv.due_date && <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Dívida original: {formatDateOnly(inv.due_date)}</div>}
                  </td>
                  <td><span className={`badge ${inv.display_status || inv.status}`}>{inv.display_status_label || statusLabel(inv.status)}</span></td>
                  <td><span>{whatsappLabel(inv.whatsapp_status)}</span><div style={{ fontSize: 12, color: 'var(--text-muted)', maxWidth: 240 }}>{inv.whatsapp_detail || inv.whatsapp_block_reason}</div></td>
                  <td>
                    <div style={{ display: 'flex', gap: 8 }}>
                      {canSendWhatsApp && (
                        <button className="btn btn-ghost btn-icon btn-sm" disabled={busy || !!loadError} onClick={(e) => sendWhatsApp(inv.id, e)} title="Encaminhar via WhatsApp">
                          {sendingId === inv.id ? <Loader2 size={14} className="spinner" /> : <MessageCircleMore size={14} />}
                        </button>
                      )}
                      {(inv.has_pdf || inv.efi_pdf_url) && (
                        <button className="btn btn-ghost btn-icon btn-sm" onClick={(e) => downloadPdf(inv.id, e)} title="Download PDF">
                          <Download size={14} />
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="pagination">
          <span>Página {page} de {totalPages}</span>
          <div className="pagination-buttons">
            <button aria-label="Página anterior" className="btn btn-secondary btn-sm" disabled={busy || loading || page <= 1} onClick={() => { setSelected([]); setSendFeedback({}); setPage(p => p - 1); }}><ChevronLeft size={14} /></button>
            <button aria-label="Próxima página" className="btn btn-secondary btn-sm" disabled={busy || loading || page >= totalPages} onClick={() => { setSelected([]); setSendFeedback({}); setPage(p => p + 1); }}><ChevronRight size={14} /></button>
          </div>
        </div>
      )}
    </>
  );
}

function statusLabel(s: string) {
  const m: Record<string, string> = { upcoming: 'A vencer', due_today: 'Vence hoje', pending: 'Pendente', sent: 'Emitida', paid: 'Pago', overdue: 'Vencido', cancelled: 'Cancelado' };
  return m[s] || s;
}

function canSend(invoice: Invoice) {
  return ['pending', 'sent', 'overdue'].includes(invoice.status) && !invoice.whatsapp_block_reason && !['sent', 'delivered', 'read'].includes(invoice.whatsapp_status || '');
}

function whatsappLabel(status: string | null) {
  const labels: Record<string, string> = { queued: 'Na fila', sent: 'Enviada', delivered: 'Entregue', read: 'Lida', failed: 'Não enviada' };
  return status ? labels[status] || status : 'Sem envio registrado';
}
