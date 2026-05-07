'use client';

import { useEffect, useState, use } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { ArrowLeft, Droplets, FileText, MapPin, Calendar, Edit2 } from 'lucide-react';

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
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      api.get<Customer>(`/customers/${id}`),
      api.get<{ items: Invoice[] }>(`/invoices?customer_id=${id}&per_page=10`),
    ]).then(([c, inv]) => {
      setCustomer(c);
      setInvoices(inv.items);
    }).catch(console.error).finally(() => setLoading(false));
  }, [id]);

  if (loading || !customer) return <div className="loading-page"><div className="spinner" style={{ width: 32, height: 32 }} /></div>;

  return (
    <>
      <Header title={customer.name} subtitle={`CPF/CNPJ: ${customer.cpf_cnpj}`} actions={
        <button className="btn btn-secondary btn-sm" onClick={() => router.push(`/customers/${id}/edit`)}><Edit2 size={14} /> Editar</button>
      } />

      <button className="btn btn-ghost btn-sm" onClick={() => router.push('/customers')} style={{ marginBottom: 20 }}>
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
          <span className="card-title">Últimas Faturas</span>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{customer.total_invoices} total</span>
        </div>
        <div className="table-wrapper" style={{ border: 'none' }}>
          <table className="data-table">
            <thead><tr><th>Referência</th><th>Consumo</th><th>Valor</th><th>Vencimento</th><th>Status</th></tr></thead>
            <tbody>
              {invoices.length === 0 ? (
                <tr><td colSpan={5}><div className="empty-state" style={{ padding: 24 }}><p>Nenhuma fatura</p></div></td></tr>
              ) : invoices.map(inv => (
                <tr key={inv.id} onClick={() => router.push(`/invoices/${inv.id}`)} style={{ cursor: 'pointer' }}>
                  <td className="cell-primary">{inv.reference_month}</td>
                  <td>{inv.consumption_m3.toFixed(2)} m³</td>
                  <td style={{ fontWeight: 600 }}>{fmt(inv.amount)}</td>
                  <td>{new Date(inv.due_date).toLocaleDateString('pt-BR')}</td>
                  <td><span className={`badge ${inv.status}`}>{statusLabel(inv.status)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
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
