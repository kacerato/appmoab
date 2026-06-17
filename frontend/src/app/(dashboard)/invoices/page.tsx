'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { useAppFeedback } from '@/components/AppFeedbackProvider';
import { Download, ChevronLeft, ChevronRight, MessageCircleMore, Loader2 } from 'lucide-react';

interface Invoice {
  id: string;
  customer_name: string;
  customer_cpf_cnpj: string;
  amount: number;
  consumption_m3: number;
  tariff_rate: number;
  due_date: string;
  paid_date: string;
  status: string;
  display_status: string | null;
  display_status_label: string | null;
  days_until_due: number | null;
  reference_month: string;
  has_pdf: boolean;
  efi_pdf_url: string | null;
  efi_payment_url: string | null;
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
  const { notify } = useAppFeedback();
  const [data, setData] = useState<ListRes | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [page, setPage] = useState(1);
  const [sendingId, setSendingId] = useState<string | null>(null);
  const [sendFeedback, setSendFeedback] = useState<Record<string, WhatsAppDispatchResult>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      let url = `/invoices?page=${page}&per_page=20`;
      if (filter) url += `&status=${filter}`;
      setData(await api.get<ListRes>(url));
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [page, filter]);

  useEffect(() => {
    load();
  }, [load]);

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
    setSendingId(id);
    try {
      const result = await api.post<WhatsAppDispatchResult>(`/invoices/${id}/send-whatsapp`);
      setSendFeedback(current => ({ ...current, [id]: result }));
      if (result.status === 'sent') {
        await load();
      }
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
      setSendingId(null);
    }
  };

  const totalPages = data ? Math.ceil(data.total / data.per_page) : 0;

  return (
    <>
      <Header title="Faturas" subtitle={`${data?.total || 0} registros`} />

      <div className="toolbar">
        {[
          { v: '', l: 'Todas' },
          { v: 'upcoming', l: 'A vencer' },
          { v: 'pending', l: 'Pendentes' },
          { v: 'sent', l: 'Enviadas' },
          { v: 'paid', l: 'Pagas' },
          { v: 'overdue', l: 'Vencidas' },
          { v: 'cancelled', l: 'Canceladas' },
        ].map(f => (
          <button key={f.v} className={`btn ${filter === f.v ? 'btn-primary' : 'btn-secondary'} btn-sm`} onClick={() => { setFilter(f.v); setPage(1); }}>
            {f.l}
          </button>
        ))}
      </div>

      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr><th>Cliente</th><th>Ref</th><th>Consumo</th><th>Valor</th><th>Vencimento</th><th>Status</th><th>Ações</th></tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7}><div className="loading-page" style={{ height: 200 }}><div className="spinner" /></div></td></tr>
            ) : !data?.items.length ? (
              <tr><td colSpan={7}><div className="empty-state"><p>Nenhuma fatura encontrada</p></div></td></tr>
            ) : data.items.map(inv => {
              const feedback = sendFeedback[inv.id];
              const canSendWhatsApp = ['pending', 'sent', 'overdue'].includes(inv.status);

              return (
                <tr key={inv.id} onClick={() => router.push(`/faturas/${inv.id}`)} style={{ cursor: 'pointer' }}>
                  <td className="cell-primary">
                    {inv.customer_name}
                    {feedback && (
                      <div style={{ fontSize: 11, fontWeight: 500, color: feedback.status === 'sent' ? 'var(--success)' : 'var(--danger)', marginTop: 4 }}>
                        {feedback.detail}
                      </div>
                    )}
                  </td>
                  <td>{inv.reference_month}</td>
                  <td>{inv.consumption_m3.toFixed(2)} m³</td>
                  <td style={{ fontWeight: 700 }}>{fmt(inv.amount)}</td>
                  <td>{formatDateOnly(inv.due_date)}</td>
                  <td><span className={`badge ${inv.display_status || inv.status}`}>{inv.display_status_label || statusLabel(inv.status)}</span></td>
                  <td>
                    <div style={{ display: 'flex', gap: 8 }}>
                      {canSendWhatsApp && (
                        <button className="btn btn-ghost btn-icon btn-sm" onClick={(e) => sendWhatsApp(inv.id, e)} title="Encaminhar via WhatsApp">
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
            <button className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}><ChevronLeft size={14} /></button>
            <button className="btn btn-secondary btn-sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}><ChevronRight size={14} /></button>
          </div>
        </div>
      )}
    </>
  );
}

function statusLabel(s: string) {
  const m: Record<string, string> = { upcoming: 'A vencer', due_today: 'Vence hoje', pending: 'Pendente', sent: 'Enviado', paid: 'Pago', overdue: 'Vencido', cancelled: 'Cancelado' };
  return m[s] || s;
}
