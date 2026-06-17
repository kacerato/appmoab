'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import {
  Users, FileText, AlertTriangle, DollarSign,
  ClipboardCheck, Droplets, TrendingUp, TrendingDown, Settings
} from 'lucide-react';
import Link from 'next/link';

interface DashboardData {
  customers: { total: number; active: number; with_hydrometer: number; without_hydrometer: number };
  financial: {
    pending_amount: number; upcoming_amount: number; overdue_amount: number; paid_this_month: number;
    pending_count: number; upcoming_count: number; overdue_count: number; paid_count: number;
    deductions: { total: number; items: { label: string; amount: number }[] };
  };
  readings: { pending_approval: number; this_month: number };
  operational_issues: Array<{
    code: string;
    title: string;
    detail: string;
    severity: 'danger' | 'warning' | 'info';
    href: string;
  }>;
  current_month: string;
  scope: 'month' | 'all';
}

function fmt(v: number) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v);
}

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [scope, setScope] = useState<'month' | 'all'>('month');

  useEffect(() => {
    api.get<DashboardData>(`/dashboard?scope=${scope}`)
      .then(setData)
      .catch(console.error);
  }, [scope]);

  if (!data) {
    return (
      <>
        <Header title="Dashboard" subtitle="Visão geral do sistema" />
        <div className="kpi-grid">
          {[...Array(6)].map((_, i) => (
            <div key={i} className="kpi-card blue"><div className="skeleton" style={{ height: 20, width: '60%', marginBottom: 8 }} /><div className="skeleton" style={{ height: 36, width: '40%' }} /></div>
          ))}
        </div>
      </>
    );
  }

  const netRevenue = data.financial.paid_this_month - data.financial.deductions.total;

  return (
    <>
      <Header
        title="Dashboard"
        subtitle={scope === 'all' ? 'Visão acumulada de todos os registros' : `Referência: ${data.current_month}`}
        actions={(
          <div className="toolbar" style={{ margin: 0, padding: 0 }}>
            <button className={`btn ${scope === 'month' ? 'btn-primary' : 'btn-secondary'} btn-sm`} onClick={() => setScope('month')}>Mês</button>
            <button className={`btn ${scope === 'all' ? 'btn-primary' : 'btn-secondary'} btn-sm`} onClick={() => setScope('all')}>Total</button>
          </div>
        )}
      />

      <div className="kpi-grid">
        <div className="kpi-card blue">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div className="kpi-icon blue"><Users size={20} /></div>
            <span className="badge active">{data.customers.active} ativos</span>
          </div>
          <div className="kpi-label">Total de Clientes</div>
          <div className="kpi-value">{data.customers.total}</div>
          <div className="kpi-sub">
            {data.customers.with_hydrometer} com hidrômetro · {data.customers.without_hydrometer} sem
          </div>
        </div>

        <div className="kpi-card green">
          <div className="kpi-icon green"><DollarSign size={20} /></div>
          <div className="kpi-label">{scope === 'all' ? 'Recebido total' : 'Recebido este mês'}</div>
          <div className="kpi-value" style={{ color: 'var(--success)' }}>{fmt(data.financial.paid_this_month)}</div>
          <div className="kpi-sub">{data.financial.paid_count} faturas pagas</div>
        </div>

        <div className="kpi-card orange">
          <div className="kpi-icon orange"><FileText size={20} /></div>
          <div className="kpi-label">Pendente Hoje</div>
          <div className="kpi-value" style={{ color: 'var(--warning)' }}>{fmt(data.financial.pending_amount)}</div>
          <div className="kpi-sub">{data.financial.pending_count} fatura(s) no vencimento</div>
        </div>

        <div className="kpi-card red">
          <div className="kpi-icon red"><AlertTriangle size={20} /></div>
          <div className="kpi-label">Inadimplência</div>
          <div className="kpi-value" style={{ color: 'var(--danger)' }}>{fmt(data.financial.overdue_amount)}</div>
          <div className="kpi-sub">{data.financial.overdue_count} faturas vencidas</div>
        </div>

        <div className="kpi-card cyan">
          <div className="kpi-icon cyan"><ClipboardCheck size={20} /></div>
          <div className="kpi-label">Leituras Pendentes</div>
          <div className="kpi-value">{data.readings.pending_approval}</div>
          <div className="kpi-sub">{data.readings.this_month} leituras {scope === 'all' ? 'no total' : 'este mês'}</div>
        </div>

        <div className="kpi-card blue">
          <div className="kpi-icon blue"><Droplets size={20} /></div>
          <div className="kpi-label">Receita Líquida</div>
          <div className="kpi-value" style={{ color: netRevenue >= 0 ? 'var(--success)' : 'var(--danger)' }}>
            {fmt(netRevenue)}
          </div>
          <div className="kpi-sub">Após deduções de {fmt(data.financial.deductions.total)}</div>
        </div>
      </div>

      {data.operational_issues?.length ? (
        <div className="card" style={{ marginBottom: 16, padding: 18 }}>
          <div className="card-header" style={{ marginBottom: 12 }}>
            <span className="card-title">Atenção operacional</span>
            <span className="badge pending">{data.operational_issues.length} item(ns)</span>
          </div>
          <div style={{ display: 'grid', gap: 8 }}>
            {data.operational_issues.slice(0, 6).map((issue, index) => (
              <Link
                key={`${issue.code}-${index}`}
                href={issue.href}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '18px minmax(0, 1fr) auto',
                  gap: 10,
                  alignItems: 'center',
                  padding: '10px 0',
                  borderTop: index ? '1px solid var(--border)' : 0,
                  color: 'inherit',
                }}
              >
                <AlertTriangle size={16} style={{ color: issue.severity === 'danger' ? 'var(--danger)' : 'var(--warning)' }} />
                <span style={{ minWidth: 0 }}>
                  <strong style={{ display: 'block', fontSize: 13 }}>{issue.title}</strong>
                  <small style={{ display: 'block', color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{issue.detail}</small>
                </span>
                <span style={{ fontSize: 11, fontWeight: 800, color: 'var(--accent)' }}>Ver</span>
              </Link>
            ))}
          </div>
        </div>
      ) : null}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="card">
          <div className="card-header">
            <span className="card-title">Resumo Financeiro</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <FinRow label="Faturado (pago)" value={data.financial.paid_this_month} color="var(--success)" icon={<TrendingUp size={14} />} />
            <FinRow label="A vencer" value={data.financial.upcoming_amount} color="var(--accent)" icon={<FileText size={14} />} />
            <FinRow label="Pendente hoje" value={data.financial.pending_amount} color="var(--warning)" icon={<FileText size={14} />} />
            <FinRow label="Inadimplente" value={data.financial.overdue_amount} color="var(--danger)" icon={<TrendingDown size={14} />} />
            <div style={{ borderTop: '1px solid var(--border)', paddingTop: 14 }}>
              <FinRow label="Receita líquida" value={netRevenue} color={netRevenue >= 0 ? 'var(--success)' : 'var(--danger)'} icon={<DollarSign size={14} />} bold />
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-header">
            <span className="card-title">Deduções Mensais</span>
            <Link href="/configuracoes" className="btn btn-ghost btn-sm"><Settings size={13} /> Configurar</Link>
          </div>
          {data.financial.deductions.items.length === 0 ? (
            <div className="empty-state" style={{ padding: 32 }}>
              <p>Nenhuma dedução cadastrada. <Link href="/configuracoes">Configure nas configurações.</Link></p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {data.financial.deductions.items.map((item, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{item.label}</span>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--danger)' }}>- {fmt(item.amount)}</span>
                </div>
              ))}
              <div style={{ borderTop: '1px solid var(--border)', paddingTop: 12, display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 13, fontWeight: 700 }}>Total</span>
                <span style={{ fontSize: 14, fontWeight: 800, color: 'var(--danger)' }}>- {fmt(data.financial.deductions.total)}</span>
              </div>
            </div>
          )}
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
        {fmt(value)}
      </span>
    </div>
  );
}
