'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import {
  Users, FileText, AlertTriangle, DollarSign,
  ClipboardCheck, Droplets, TrendingUp, TrendingDown
} from 'lucide-react';

interface DashboardData {
  customers: { total: number; active: number; with_hydrometer: number; without_hydrometer: number };
  financial: {
    pending_amount: number; overdue_amount: number; paid_this_month: number;
    pending_count: number; overdue_count: number; paid_count: number;
    deductions: { total: number; items: { label: string; amount: number }[] };
  };
  readings: { pending_approval: number; this_month: number };
  current_month: string;
}

function formatCurrency(v: number) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v);
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<DashboardData>('/dashboard')
      .then(setData)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  if (loading || !data) {
    return (
      <>
        <Header title="Dashboard" subtitle="Visão geral do sistema" />
        <div className="loading-page"><div className="spinner" style={{ width: 32, height: 32 }} /></div>
      </>
    );
  }

  const netRevenue = data.financial.paid_this_month - data.financial.deductions.total;

  return (
    <>
      <Header title="Dashboard" subtitle={`Referência: ${data.current_month}`} />

      <div className="kpi-grid">
        <div className="kpi-card blue">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div className="kpi-icon blue"><Users size={20} /></div>
            <span className="badge active">{data.customers.active} ativos</span>
          </div>
          <div className="kpi-label">Total de Clientes</div>
          <div className="kpi-value">{data.customers.total}</div>
          <div className="kpi-sub">
            {data.customers.with_hydrometer} com hidrômetro · {data.customers.without_hydrometer} sem hidrômetro
          </div>
        </div>

        <div className="kpi-card green">
          <div className="kpi-icon green"><DollarSign size={20} /></div>
          <div className="kpi-label">Recebido este mês</div>
          <div className="kpi-value" style={{ color: 'var(--success)' }}>{formatCurrency(data.financial.paid_this_month)}</div>
          <div className="kpi-sub">{data.financial.paid_count} faturas pagas</div>
        </div>

        <div className="kpi-card orange">
          <div className="kpi-icon orange"><FileText size={20} /></div>
          <div className="kpi-label">A Receber</div>
          <div className="kpi-value" style={{ color: 'var(--warning)' }}>{formatCurrency(data.financial.pending_amount)}</div>
          <div className="kpi-sub">{data.financial.pending_count} faturas pendentes</div>
        </div>

        <div className="kpi-card red">
          <div className="kpi-icon red"><AlertTriangle size={20} /></div>
          <div className="kpi-label">Inadimplência</div>
          <div className="kpi-value" style={{ color: 'var(--danger)' }}>{formatCurrency(data.financial.overdue_amount)}</div>
          <div className="kpi-sub">{data.financial.overdue_count} faturas vencidas</div>
        </div>

        <div className="kpi-card cyan">
          <div className="kpi-icon cyan"><ClipboardCheck size={20} /></div>
          <div className="kpi-label">Leituras Pendentes</div>
          <div className="kpi-value">{data.readings.pending_approval}</div>
          <div className="kpi-sub">{data.readings.this_month} leituras este mês</div>
        </div>

        <div className="kpi-card blue">
          <div className="kpi-icon blue"><Droplets size={20} /></div>
          <div className="kpi-label">Receita Líquida</div>
          <div className="kpi-value" style={{ color: netRevenue >= 0 ? 'var(--success)' : 'var(--danger)' }}>
            {formatCurrency(netRevenue)}
          </div>
          <div className="kpi-sub">Após deduções de {formatCurrency(data.financial.deductions.total)}</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="card">
          <div className="card-header">
            <span className="card-title">Resumo Financeiro</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <FinRow label="Faturado (pago)" value={data.financial.paid_this_month} color="var(--success)" icon={<TrendingUp size={14} />} />
            <FinRow label="A receber" value={data.financial.pending_amount} color="var(--warning)" icon={<FileText size={14} />} />
            <FinRow label="Inadimplente" value={data.financial.overdue_amount} color="var(--danger)" icon={<TrendingDown size={14} />} />
            <div style={{ borderTop: '1px solid var(--border)', paddingTop: 14 }}>
              <FinRow label="Receita líquida" value={netRevenue} color={netRevenue >= 0 ? 'var(--success)' : 'var(--danger)'} icon={<DollarSign size={14} />} bold />
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Deduções Mensais</span>
            <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Total: {formatCurrency(data.financial.deductions.total)}</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {data.financial.deductions.items.map((item, i) => (
              <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{item.label}</span>
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--danger)' }}>- {formatCurrency(item.amount)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  );
}

function FinRow({ label, value, color, icon, bold }: { label: string; value: number; color: string; icon: React.ReactNode; bold?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--text-secondary)', fontSize: 13 }}>
        <span style={{ color }}>{icon}</span>
        {label}
      </div>
      <span style={{ fontSize: bold ? 16 : 14, fontWeight: bold ? 800 : 600, color }}>
        {formatCurrency(value)}
      </span>
    </div>
  );
}
