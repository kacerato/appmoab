'use client';

import { useEffect, useState, FormEvent } from 'react';
import Header from '@/components/Header';
import { api } from '@/lib/api';
import { Database, Globe, Key, Server, Plus, Pencil, Trash2, Save, X, Loader2 } from 'lucide-react';

interface Deduction {
  id: string;
  label: string;
  amount: number;
  is_active: boolean;
  sort_order: number;
}

function fmt(v: number) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v);
}

export default function SettingsPage() {
  const [deductions, setDeductions] = useState<Deduction[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [editId, setEditId] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ label: '', amount: '' });
  const [saving, setSaving] = useState(false);

  const load = () => {
    api.get<{ items: Deduction[]; total: number }>('/deductions')
      .then(res => { setDeductions(res.items); setTotal(res.total); })
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleAdd = async (e: FormEvent) => {
    e.preventDefault();
    if (!form.label || !form.amount) return;
    setSaving(true);
    try {
      await api.post('/deductions', { label: form.label, amount: parseFloat(form.amount), sort_order: deductions.length });
      setForm({ label: '', amount: '' });
      setShowAdd(false);
      load();
    } catch (err) { console.error(err); }
    finally { setSaving(false); }
  };

  const handleUpdate = async (id: string) => {
    if (!form.label || !form.amount) return;
    setSaving(true);
    try {
      await api.patch(`/deductions/${id}`, { label: form.label, amount: parseFloat(form.amount) });
      setEditId(null);
      setForm({ label: '', amount: '' });
      load();
    } catch (err) { console.error(err); }
    finally { setSaving(false); }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Remover esta dedução?')) return;
    try { await api.delete(`/deductions/${id}`); load(); }
    catch (err) { console.error(err); }
  };

  const startEdit = (d: Deduction) => {
    setEditId(d.id);
    setForm({ label: d.label, amount: d.amount.toString() });
    setShowAdd(false);
  };

  return (
    <>
      <Header title="Configurações" subtitle="Parâmetros do sistema" />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <SettingCard icon={<Database size={18} />} title="Banco de Dados" desc="Neon PostgreSQL Serverless" status="Conectado" statusColor="var(--success)" />
        <SettingCard icon={<Key size={18} />} title="Banco Inter" desc="API Cobrança V3 — Sandbox" status="Configurado" statusColor="var(--success)" />
        <SettingCard icon={<Globe size={18} />} title="WhatsApp" desc="Cloud API — Aguardando número" status="Desativado" statusColor="var(--warning)" />
        <SettingCard icon={<Server size={18} />} title="Kimi K2.6 Vision" desc="OCR de hidrômetros — Moonshot AI" status="Configurado" statusColor="var(--success)" />
      </div>

      {/* Deduções Configuráveis */}
      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-header">
          <span className="card-title">Deduções Mensais</span>
          <button className="btn btn-primary btn-sm" onClick={() => { setShowAdd(true); setEditId(null); setForm({ label: '', amount: '' }); }}>
            <Plus size={14} /> Nova Dedução
          </button>
        </div>

        {showAdd && (
          <form onSubmit={handleAdd} style={{ display: 'flex', gap: 10, marginBottom: 16, padding: 14, background: 'var(--blue-50)', borderRadius: 'var(--radius-md)' }}>
            <input className="form-input" placeholder="Nome (ex: Energia)" value={form.label} onChange={e => setForm(f => ({ ...f, label: e.target.value }))} style={{ flex: 2 }} required />
            <input className="form-input" placeholder="Valor" type="number" step="0.01" value={form.amount} onChange={e => setForm(f => ({ ...f, amount: e.target.value }))} style={{ flex: 1 }} required />
            <button className="btn btn-primary btn-sm" type="submit" disabled={saving}>
              {saving ? <Loader2 size={14} className="spinner" /> : <Save size={14} />} Salvar
            </button>
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => setShowAdd(false)}><X size={14} /></button>
          </form>
        )}

        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[...Array(3)].map((_, i) => <div key={i} className="skeleton" style={{ height: 40 }} />)}
          </div>
        ) : deductions.length === 0 ? (
          <div className="empty-state" style={{ padding: 32 }}>
            <p>Nenhuma dedução cadastrada. Clique em &quot;Nova Dedução&quot; para começar.</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {deductions.map(d => (
              <div key={d.id}>
                {editId === d.id ? (
                  <div style={{ display: 'flex', gap: 10, padding: 10, background: 'var(--blue-50)', borderRadius: 'var(--radius-md)' }}>
                    <input className="form-input" value={form.label} onChange={e => setForm(f => ({ ...f, label: e.target.value }))} style={{ flex: 2 }} />
                    <input className="form-input" type="number" step="0.01" value={form.amount} onChange={e => setForm(f => ({ ...f, amount: e.target.value }))} style={{ flex: 1 }} />
                    <button className="btn btn-primary btn-sm" onClick={() => handleUpdate(d.id)} disabled={saving}>
                      {saving ? <Loader2 size={14} className="spinner" /> : <Save size={14} />}
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setEditId(null)}><X size={14} /></button>
                  </div>
                ) : (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 4px', borderBottom: '1px solid var(--border)' }}>
                    <span style={{ fontSize: 14, color: 'var(--text-primary)' }}>{d.label}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--danger)' }}>- {fmt(d.amount)}</span>
                      <button className="btn btn-ghost btn-icon btn-sm" onClick={() => startEdit(d)}><Pencil size={13} /></button>
                      <button className="btn btn-ghost btn-icon btn-sm" onClick={() => handleDelete(d.id)} style={{ color: 'var(--danger)' }}><Trash2 size={13} /></button>
                    </div>
                  </div>
                )}
              </div>
            ))}
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '14px 4px 4px', fontWeight: 700 }}>
              <span>Total mensal</span>
              <span style={{ color: 'var(--danger)' }}>- {fmt(total)}</span>
            </div>
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-header"><span className="card-title">Informações do Sistema</span></div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13, color: 'var(--text-secondary)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Versão</span><span style={{ fontWeight: 600 }}>1.0.0</span></div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Backend</span><span style={{ fontWeight: 600 }}>FastAPI (Python)</span></div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Frontend</span><span style={{ fontWeight: 600 }}>Next.js 16</span></div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Deploy</span><span style={{ fontWeight: 600 }}>Vercel + Railway</span></div>
        </div>
      </div>
    </>
  );
}

function SettingCard({ icon, title, desc, status, statusColor }: {
  icon: React.ReactNode; title: string; desc: string; status: string; statusColor: string;
}) {
  return (
    <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
      <div className="kpi-icon blue" style={{ width: 44, height: 44, flexShrink: 0 }}>{icon}</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>{title}</div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{desc}</div>
      </div>
      <div style={{ fontSize: 12, fontWeight: 600, color: statusColor }}>{status}</div>
    </div>
  );
}
