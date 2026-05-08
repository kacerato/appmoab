'use client';

import { useEffect, useState, use, FormEvent, useMemo, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { useAppFeedback } from '@/components/AppFeedbackProvider';
import { ArrowLeft, Droplets, MapPin, Calendar, Edit2, Trash2, Plus, X, Loader2 } from 'lucide-react';

interface Customer {
  id: string; name: string; cpf_cnpj: string; phone: string; email: string;
  address: string; number: string; complement: string; neighborhood: string;
  city: string; state: string; zip_code: string; due_day: number;
  has_hydrometer: boolean; status: string; notes: string; created_at: string;
  hydrometers: Hydrometer[]; total_invoices: number; total_pending: number; total_overdue: number;
}

interface Hydrometer { id: string; code: string; last_reading_value: number; last_reading_date: string; is_active: boolean; }
interface Invoice { id: string; amount: number; due_date: string; status: string; reference_month: string; consumption_m3: number; }

function fmt(v: number) { return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v); }

export default function CustomerDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { confirm, notify } = useAppFeedback();
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [showInvoiceModal, setShowInvoiceModal] = useState(false);
  const [savingInvoice, setSavingInvoice] = useState(false);

  const [invoiceForm, setInvoiceForm] = useState({
    amount: '',
    reference_month: new Date().toISOString().slice(0, 7), // YYYY-MM
    due_date: new Date().toISOString().slice(0, 10), // YYYY-MM-DD
    consumption_m3: '',
    auto_amount: false,
  });

  const consumptionValue = useMemo(() => parseFloat(invoiceForm.consumption_m3 || '0'), [invoiceForm.consumption_m3]);

  const load = useCallback(() => {
    Promise.all([
      api.get<Customer>(`/customers/${id}`),
      api.get<{ items: Invoice[] }>(`/invoices?customer_id=${id}&per_page=10`),
    ]).then(([c, inv]) => {
      setCustomer(c);
      setInvoices(inv.items);
    }).catch(console.error).finally(() => setLoading(false));
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const handleDelete = async () => {
    const confirmed = await confirm('Remover cliente', 'Deseja realmente desligar ou remover este cliente?', {
      confirmLabel: 'Remover',
    });
    if (!confirmed) return;
    try {
      await api.delete(`/customers/${id}`);
      notify('Cliente removido', 'O cadastro foi encerrado com sucesso.', 'success');
      router.push('/clientes');
    } catch (err: unknown) {
      notify('Falha ao excluir cliente', err instanceof Error ? err.message : 'Erro ao excluir.', 'error');
    }
  };

  const handleCreateInvoice = async (e: FormEvent) => {
    e.preventDefault();
    setSavingInvoice(true);
    try {
      await api.post('/invoices/manual', {
        customer_id: id,
        amount: parseFloat(invoiceForm.amount),
        reference_month: invoiceForm.reference_month,
        due_date: invoiceForm.due_date,
        consumption_m3: consumptionValue || 0,
      });
      setShowInvoiceModal(false);
      load();
      notify('Cobrança avulsa criada', 'A nova fatura foi gerada para o cliente.', 'success');
    } catch (err: unknown) {
      notify('Falha ao gerar cobrança', err instanceof Error ? err.message : 'Erro ao gerar fatura avulsa.', 'error');
    } finally {
      setSavingInvoice(false);
    }
  };

  useEffect(() => {
    if (!invoiceForm.auto_amount || !consumptionValue || Number.isNaN(consumptionValue)) return;
    let active = true;
    api.get<{ final_amount: number }>(`/tariffs/simulate/${consumptionValue}`)
      .then(res => {
        if (active) {
          setInvoiceForm(current => ({ ...current, amount: res.final_amount.toFixed(2) }));
        }
      })
      .catch(() => {
        // Keep manual value if simulation fails.
      });
    return () => {
      active = false;
    };
  }, [invoiceForm.auto_amount, consumptionValue]);

  if (loading || !customer) return <div className="loading-page"><div className="spinner" style={{ width: 32, height: 32 }} /></div>;

  return (
    <>
      <Header title={customer.name} subtitle={`CPF/CNPJ: ${customer.cpf_cnpj}`} actions={
        <div style={{ display: 'flex', gap: 10 }}>
          <button className="btn btn-secondary btn-sm" onClick={() => router.push(`/clientes/${id}/editar`)}>
            <Edit2 size={14} /> Editar
          </button>
          <button className="btn btn-danger btn-sm" onClick={handleDelete}>
            <Trash2 size={14} /> Excluir
          </button>
        </div>
      } />

      <button className="btn btn-ghost btn-sm" onClick={() => router.push('/clientes')} style={{ marginBottom: 20 }}>
        <ArrowLeft size={14} /> Voltar
      </button>

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <div className="kpi-card blue">
          <div className="kpi-label">Status</div>
          <span className={`badge ${customer.status}`}>{customer.status === 'active' ? 'Ativo' : customer.status === 'suspended' ? 'Suspenso' : 'Desligado'}</span>
        </div>
        <div className="kpi-card cyan">
          <div className="kpi-label">Tipo</div>
          <div className="kpi-value" style={{ fontSize: 18 }}>{customer.has_hydrometer ? 'Medido' : 'Fixo R$100'}</div>
        </div>
        <div className="kpi-card orange">
          <div className="kpi-label">Pendente</div>
          <div className="kpi-value" style={{ fontSize: 20, color: 'var(--warning)' }}>{fmt(customer.total_pending)}</div>
        </div>
        <div className="kpi-card red">
          <div className="kpi-label">Em Atraso</div>
          <div className="kpi-value" style={{ fontSize: 20, color: 'var(--danger)' }}>{fmt(customer.total_overdue)}</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
        <div className="card">
          <div className="card-header"><span className="card-title">Informações</span></div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 13 }}>
            <Info icon={<MapPin size={14} />} label="Endereço" value={`${customer.address}, ${customer.number} - ${customer.neighborhood}, ${customer.city}/${customer.state}`} />
            <Info icon={<Calendar size={14} />} label="Dia de Vencimento" value={`Dia ${customer.due_day} de cada mês`} />
            {customer.phone && <Info icon={<span>📱</span>} label="Telefone" value={customer.phone} />}
            {customer.email && <Info icon={<span>✉️</span>} label="Email" value={customer.email} />}
            {customer.notes && <Info icon={<span>📝</span>} label="Observações" value={customer.notes} />}
          </div>
        </div>

        <div className="card">
          <div className="card-header"><span className="card-title">Hidrômetros</span></div>
          {customer.hydrometers.length === 0 ? (
            <div className="empty-state" style={{ padding: 32 }}><p>{customer.has_hydrometer ? 'Nenhum hidrômetro cadastrado' : 'Cliente sem hidrômetro (taxa fixa)'}</p></div>
          ) : customer.hydrometers.map(h => (
            <div key={h.id} style={{ padding: '12px 0', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 12 }}>
              <div className="kpi-icon cyan" style={{ width: 36, height: 36 }}><Droplets size={16} /></div>
              <div>
                <div style={{ fontWeight: 600, fontSize: 14 }}>{h.code}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  Última leitura: {h.last_reading_value.toFixed(2)} m³
                  {h.last_reading_date && ` em ${new Date(h.last_reading_date).toLocaleDateString('pt-BR')}`}
                </div>
              </div>
              <span className={`badge ${h.is_active ? 'active' : 'suspended'}`} style={{ marginLeft: 'auto' }}>
                {h.is_active ? 'Ativo' : 'Inativo'}
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <div>
            <span className="card-title">Últimas Faturas</span>
            <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>{customer.total_invoices} total</span>
          </div>
          <button className="btn btn-primary btn-sm" onClick={() => setShowInvoiceModal(true)}>
            <Plus size={14} /> Cobrança Avulsa
          </button>
        </div>
        <div className="table-wrapper" style={{ border: 'none' }}>
          <table className="data-table">
            <thead><tr><th>Referência</th><th>Consumo</th><th>Valor</th><th>Vencimento</th><th>Status</th></tr></thead>
            <tbody>
              {invoices.length === 0 ? (
                <tr><td colSpan={5}><div className="empty-state" style={{ padding: 24 }}><p>Nenhuma fatura</p></div></td></tr>
              ) : invoices.map(inv => (
                <tr key={inv.id} onClick={() => router.push(`/faturas/${inv.id}`)} style={{ cursor: 'pointer' }}>
                  <td className="cell-primary">{inv.reference_month}</td>
                  <td>{inv.consumption_m3 > 0 ? `${inv.consumption_m3.toFixed(2)} m³` : 'Fixo / Avulso'}</td>
                  <td style={{ fontWeight: 600 }}>{fmt(inv.amount)}</td>
                  <td>{new Date(inv.due_date).toLocaleDateString('pt-BR')}</td>
                  <td><span className={`badge ${inv.status}`}>{statusLabel(inv.status)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {showInvoiceModal && (
        <div className="modal-overlay">
          <div className="modal" style={{ maxWidth: 400 }}>
            <div className="modal-header">
              <h2 className="modal-title">Gerar Boleto / Fatura Avulsa</h2>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowInvoiceModal(false)}><X size={20} /></button>
            </div>
            <form onSubmit={handleCreateInvoice}>
              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Valor (R$)</label>
                <input
                  className="form-input"
                  type="number"
                  step="0.01"
                  min="0.01"
                  value={invoiceForm.amount}
                  onChange={e => setInvoiceForm({ ...invoiceForm, amount: e.target.value })}
                  required
                />
              </div>

              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Consumo associado (m³)</label>
                <input
                  className="form-input"
                  type="number"
                  step="0.01"
                  min="0"
                  value={invoiceForm.consumption_m3}
                  onChange={e => setInvoiceForm({ ...invoiceForm, consumption_m3: e.target.value })}
                  placeholder="Opcional"
                />
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
                  <input
                    type="checkbox"
                    checked={invoiceForm.auto_amount}
                    onChange={e => setInvoiceForm({ ...invoiceForm, auto_amount: e.target.checked })}
                  />
                  Calcular valor automaticamente pela tabela quando houver consumo
                </label>
              </div>

              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Mês de Referência</label>
                <input
                  className="form-input"
                  type="month"
                  value={invoiceForm.reference_month}
                  onChange={e => setInvoiceForm({ ...invoiceForm, reference_month: e.target.value })}
                  required
                />
              </div>

              <div className="form-group" style={{ marginBottom: 24 }}>
                <label className="form-label">Data de Vencimento</label>
                <input
                  className="form-input"
                  type="date"
                  value={invoiceForm.due_date}
                  onChange={e => setInvoiceForm({ ...invoiceForm, due_date: e.target.value })}
                  required
                />
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-ghost" onClick={() => setShowInvoiceModal(false)}>Cancelar</button>
                <button type="submit" className="btn btn-primary" disabled={savingInvoice || !invoiceForm.amount}>
                  {savingInvoice ? <Loader2 size={16} className="spinner" /> : 'Gerar Boleto'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

function Info({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
      <span style={{ color: 'var(--text-muted)', marginTop: 2 }}>{icon}</span>
      <div><div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 2 }}>{label}</div><div>{value}</div></div>
    </div>
  );
}

function statusLabel(s: string) {
  const m: Record<string, string> = { pending: 'Pendente', sent: 'Enviado', paid: 'Pago', overdue: 'Vencido', cancelled: 'Cancelado' };
  return m[s] || s;
}
