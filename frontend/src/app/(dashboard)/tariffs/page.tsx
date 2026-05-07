'use client';

import { useEffect, useState, useCallback } from 'react';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { DollarSign, Plus, Edit2, Calculator, Save, X, Loader2 } from 'lucide-react';

interface Tier {
  id: string; label: string; min_m3: number; max_m3: number;
  rate_per_m3: number; minimum_charge: number; fixed_rate: number;
  sort_order: number; is_active: boolean;
}

interface BillingCalc {
  consumption_m3: number; tariff_tier_label: string; tariff_rate: number;
  gross_amount: number; minimum_charge: number; final_amount: number; is_minimum_applied: boolean;
}

function fmt(v: number) { return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v); }

export default function TariffsPage() {
  const [tiers, setTiers] = useState<Tier[]>([]);
  const [loading, setLoading] = useState(true);
  const [simValue, setSimValue] = useState('15');
  const [simResult, setSimResult] = useState<BillingCalc | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editRate, setEditRate] = useState('');

  const load = useCallback(async () => {
    try {
      const res = await api.get<{ items: Tier[] }>('/tariffs');
      setTiers(res.items);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);

  const simulate = async () => {
    try {
      const res = await api.get<BillingCalc>(`/tariffs/simulate/${simValue}`);
      setSimResult(res);
    } catch (e) { console.error(e); }
  };

  const saveRate = async (id: string) => {
    try {
      await api.patch(`/tariffs/${id}`, { rate_per_m3: parseFloat(editRate) });
      setEditing(null);
      load();
    } catch (e) { alert(e instanceof Error ? e.message : 'Erro'); }
  };

  return (
    <>
      <Header title="Tarifas" subtitle="Faixas de cobrança por consumo" />

      {/* Simulador */}
      <div className="card" style={{ marginBottom: 24 }}>
        <div className="card-header">
          <span className="card-title">Simulador de Faturamento</span>
          <Calculator size={16} style={{ color: 'var(--text-muted)' }} />
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
          <div className="form-group" style={{ flex: 1, maxWidth: 200 }}>
            <label className="form-label">Consumo (m³)</label>
            <input className="form-input" type="number" value={simValue} onChange={e => setSimValue(e.target.value)} />
          </div>
          <button className="btn btn-primary" onClick={simulate}>Calcular</button>
        </div>
        {simResult && (
          <div style={{ marginTop: 16, padding: 16, background: 'var(--navy-900)', borderRadius: 'var(--radius-md)', display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
            <div><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Faixa</div><div style={{ fontWeight: 600 }}>{simResult.tariff_tier_label}</div></div>
            <div><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Tarifa</div><div style={{ fontWeight: 600 }}>R$ {simResult.tariff_rate.toFixed(2)}/m³</div></div>
            <div><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Bruto</div><div style={{ fontWeight: 600 }}>{fmt(simResult.gross_amount)}</div></div>
            <div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Valor Final</div>
              <div style={{ fontWeight: 800, fontSize: 18, color: 'var(--accent)' }}>{fmt(simResult.final_amount)}</div>
              {simResult.is_minimum_applied && <div style={{ fontSize: 11, color: 'var(--warning)' }}>Mínimo aplicado</div>}
            </div>
          </div>
        )}
      </div>

      {/* Tabela */}
      <div className="table-wrapper">
        <table className="data-table">
          <thead><tr><th>#</th><th>Faixa</th><th>De</th><th>Até</th><th>Tarifa (R$/m³)</th><th>Taxa Mínima</th><th>Ações</th></tr></thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7}><div className="loading-page" style={{ height: 150 }}><div className="spinner" /></div></td></tr>
            ) : tiers.map(t => (
              <tr key={t.id}>
                <td>{t.sort_order}</td>
                <td className="cell-primary">{t.label}</td>
                <td>{t.min_m3} m³</td>
                <td>{t.max_m3 >= 99999 ? '∞' : `${t.max_m3} m³`}</td>
                <td>
                  {editing === t.id ? (
                    <div style={{ display: 'flex', gap: 6 }}>
                      <input className="form-input" type="number" step="0.01" value={editRate} onChange={e => setEditRate(e.target.value)} style={{ width: 100, padding: '4px 8px' }} />
                      <button className="btn btn-primary btn-sm btn-icon" onClick={() => saveRate(t.id)}><Save size={12} /></button>
                      <button className="btn btn-ghost btn-sm btn-icon" onClick={() => setEditing(null)}><X size={12} /></button>
                    </div>
                  ) : (
                    <span style={{ fontWeight: 700, color: 'var(--accent)' }}>R$ {t.rate_per_m3.toFixed(2)}</span>
                  )}
                </td>
                <td>{fmt(t.minimum_charge)}</td>
                <td>
                  <button className="btn btn-ghost btn-sm btn-icon" onClick={() => { setEditing(t.id); setEditRate(t.rate_per_m3.toString()); }}>
                    <Edit2 size={13} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
