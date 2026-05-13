'use client';

/* eslint-disable react-hooks/set-state-in-effect */

import { useEffect, useState, FormEvent } from 'react';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { useAppFeedback } from '@/components/AppFeedbackProvider';
import { Droplets, Pencil, Plus, Search, Loader2, X, Download, Power, RotateCcw } from 'lucide-react';

interface Customer {
  id: string;
  name: string;
  cpf_cnpj: string;
}

interface Hydrometer {
  id: string;
  code: string;
  qr_code_token: string;
  customer_id: string;
  brand: string;
  model: string;
  red_digits: number;
  black_digits: number | null;
  location_description: string;
  last_reading_value: number;
  last_reading_date: string;
  is_active: boolean;
  installed_at: string;
  disconnected_at: string | null;
  reconnected_at: string | null;
  disconnection_reason: string | null;
  customer?: Customer;
}

export default function HydrometersPage() {
  const { notify } = useAppFeedback();
  const [items, setItems] = useState<Hydrometer[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<Hydrometer | null>(null);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState('');

  const [form, setForm] = useState({
    customer_id: '',
    code: '',
    brand: '',
    model: '',
    red_digits: 3,
    black_digits: '',
    location_description: '',
    initial_reading: 0,
  });

  const load = () => {
    setLoading(true);
    api.get<{ items: Hydrometer[] }>('/hydrometers')
      .then(r => setItems(r.items))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  const loadCustomers = () => {
    api.get<{ items: Customer[] }>('/customers?per_page=1000')
      .then(r => setCustomers(r.items.filter(c => (c as Customer & { has_hydrometer?: boolean }).has_hydrometer)))
      .catch(console.error);
  };

  useEffect(() => {
    load();
    loadCustomers();
  }, []);

  const handleAdd = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post('/hydrometers', {
        customer_id: form.customer_id,
        code: form.code.toUpperCase() || null,
        brand: form.brand || null,
        model: form.model || null,
        red_digits: form.red_digits,
        black_digits: form.black_digits === '' ? null : Number(form.black_digits),
        location_description: form.location_description || null,
        initial_reading: form.initial_reading,
      });
      setShowAdd(false);
      setForm({ customer_id: '', code: '', brand: '', model: '', red_digits: 3, black_digits: '', location_description: '', initial_reading: 0 });
      load();
      notify('Hidrômetro associado', 'O medidor foi vinculado com sucesso.', 'success');
    } catch (err: unknown) {
      notify('Falha ao associar hidrômetro', err instanceof Error ? err.message : 'Erro ao criar hidrômetro.', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    setSaving(true);
    try {
      await api.patch(`/hydrometers/${editing.id}`, {
        code: editing.code || null,
        brand: editing.brand || null,
        model: editing.model || null,
        red_digits: editing.red_digits,
        black_digits: editing.black_digits || null,
        location_description: editing.location_description || null,
        last_reading_value: editing.last_reading_value,
        is_active: editing.is_active,
      });
      setEditing(null);
      load();
      notify('Hidrômetro atualizado', 'As informações do medidor foram salvas.', 'success');
    } catch (err: unknown) {
      notify('Falha ao editar hidrômetro', err instanceof Error ? err.message : 'Erro ao salvar hidrômetro.', 'error');
    } finally {
      setSaving(false);
    }
  };

  const filteredItems = items.filter(h =>
    h.code.toLowerCase().includes(search.toLowerCase()) ||
    h.customer?.name.toLowerCase().includes(search.toLowerCase())
  );

  const downloadQr = async (hydrometer: Hydrometer) => {
    try {
      const QRCode = await import('qrcode');
      const qrValue = hydrometer.qr_code_token || hydrometer.code;
      const svg = await QRCode.toString(qrValue, {
        type: 'svg',
        margin: 2,
        width: 320,
        errorCorrectionLevel: 'M',
      });
      const blob = new Blob([svg], { type: 'image/svg+xml;charset=utf-8' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `qr_${hydrometer.customer?.name || hydrometer.code}.svg`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      notify('Falha ao baixar QR Code', err instanceof Error ? err.message : 'Nao foi possivel gerar o QR.', 'error');
    }
  };

  const disconnectHydrometer = async (hydrometer: Hydrometer) => {
    setSaving(true);
    try {
      await api.post(`/hydrometers/${hydrometer.id}/disconnect`, { reason: 'Falta de pagamento' });
      load();
      notify('Hidrômetro desligado', 'O cliente foi marcado como desligado.', 'warning');
    } catch (err: unknown) {
      notify('Falha ao desligar', err instanceof Error ? err.message : 'Erro ao desligar hidrômetro.', 'error');
    } finally {
      setSaving(false);
    }
  };

  const reconnectHydrometer = async (hydrometer: Hydrometer) => {
    setSaving(true);
    try {
      await api.post(`/hydrometers/${hydrometer.id}/reconnect`);
      load();
      notify('Religamento registrado', 'O hidrômetro foi ativado e a taxa de religamento foi gerada.', 'success');
    } catch (err: unknown) {
      notify('Falha ao religar', err instanceof Error ? err.message : 'Erro ao religar hidrômetro.', 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Header title="Hidrômetros" subtitle={`${items.length} medidores cadastrados`} />

      <div className="toolbar">
        <div className="search-box">
          <Search />
          <input
            placeholder="Buscar por código ou cliente..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
          <Plus size={16} /> Associar Novo Hidrômetro
        </button>
      </div>

      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th>Código / Cliente</th>
              <th>Marca/Modelo</th>
              <th>Mostrador</th>
              <th>Local</th>
              <th>Última Leitura</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              [...Array(5)].map((_, i) => (
                <tr key={i}>
                  <td><div className="skeleton" style={{ height: 20, width: '90%' }} /></td>
                  <td><div className="skeleton" style={{ height: 20, width: '60%' }} /></td>
                  <td><div className="skeleton" style={{ height: 20, width: '70%' }} /></td>
                  <td><div className="skeleton" style={{ height: 20, width: '40%' }} /></td>
                  <td><div className="skeleton" style={{ height: 24, width: 60, borderRadius: 99 }} /></td>
                </tr>
              ))
            ) : !filteredItems.length ? (
              <tr><td colSpan={7}><div className="empty-state"><Droplets /><p>Nenhum hidrômetro encontrado</p></div></td></tr>
            ) : filteredItems.map(h => (
              <tr key={h.id}>
                <td>
                  <div className="cell-primary" style={{ fontWeight: 800 }}>QR {h.code}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{h.customer?.name || 'Cliente desconhecido'}</div>
                </td>
                <td>{[h.brand, h.model].filter(Boolean).join(' ') || '—'}</td>
                <td>{h.red_digits || 3} vermelhos{h.black_digits ? ` · ${h.black_digits} pretos` : ''}</td>
                <td>{h.location_description || '—'}</td>
                <td>
                  <span style={{ fontWeight: 600 }}>{h.last_reading_value.toFixed(2)} m³</span>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {h.last_reading_date ? new Date(h.last_reading_date).toLocaleDateString('pt-BR') : 'Sem leituras'}
                  </div>
                </td>
                <td><span className={`badge ${h.is_active ? 'active' : 'suspended'}`}>{h.is_active ? 'Ativo' : 'Inativo'}</span></td>
                <td>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn btn-ghost btn-icon btn-sm" onClick={() => downloadQr(h)} title="Baixar QR Code">
                      <Download size={14} />
                    </button>
                    {h.is_active ? (
                      <button className="btn btn-ghost btn-icon btn-sm" onClick={() => disconnectHydrometer(h)} title="Desligar hidrômetro" disabled={saving}>
                        <Power size={14} />
                      </button>
                    ) : (
                      <button className="btn btn-ghost btn-icon btn-sm" onClick={() => reconnectHydrometer(h)} title="Religar hidrômetro" disabled={saving}>
                        <RotateCcw size={14} />
                      </button>
                    )}
                    <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setEditing(h)} title="Editar hidrômetro">
                      <Pencil size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showAdd && (
        <div className="modal-overlay">
          <div className="modal">
            <div className="modal-header">
              <h2 className="modal-title">Associar Hidrômetro</h2>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowAdd(false)}><X size={20} /></button>
            </div>
            <form onSubmit={handleAdd}>
              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Cliente Responsável</label>
                <select
                  className="form-select"
                  value={form.customer_id}
                  onChange={e => setForm({ ...form, customer_id: e.target.value })}
                  required
                >
                  <option value="">Selecione um cliente com perfil de medição...</option>
                  {customers.map(c => (
                    <option key={c.id} value={c.id}>{c.name} (CPF/CNPJ: {c.cpf_cnpj})</option>
                  ))}
                </select>
              </div>

              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Código do Hidrômetro (números)</label>
                <input
                  className="form-input"
                  placeholder="Ex: 000123 (deixe em branco para gerar)"
                  value={form.code}
                  onChange={e => setForm({ ...form, code: e.target.value.replace(/\D/g, '') })}
                  inputMode="numeric"
                  maxLength={12}
                />
              </div>

              <div className="form-grid" style={{ marginBottom: 16 }}>
                <div className="form-group">
                  <label className="form-label">Marca (Opcional)</label>
                  <input className="form-input" value={form.brand} onChange={e => setForm({ ...form, brand: e.target.value })} />
                </div>
                <div className="form-group">
                  <label className="form-label">Modelo (Opcional)</label>
                  <input className="form-input" value={form.model} onChange={e => setForm({ ...form, model: e.target.value })} />
                </div>
              </div>

              <div className="form-grid" style={{ marginBottom: 16 }}>
                <div className="form-group">
                  <label className="form-label">Dígitos vermelhos</label>
                  <select className="form-select" value={form.red_digits} onChange={e => setForm({ ...form, red_digits: Number(e.target.value) })}>
                    <option value={2}>2 dígitos vermelhos</option>
                    <option value={3}>3 dígitos vermelhos</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Dígitos pretos</label>
                  <input className="form-input" type="number" min={1} value={form.black_digits} onChange={e => setForm({ ...form, black_digits: e.target.value })} placeholder="Opcional" />
                </div>
              </div>

              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Localização no Imóvel (Opcional)</label>
                <input className="form-input" placeholder="Ex: Muro frontal esquerdo" value={form.location_description} onChange={e => setForm({ ...form, location_description: e.target.value })} />
              </div>

              <div className="form-group" style={{ marginBottom: 24 }}>
                <label className="form-label">Leitura Inicial (m³)</label>
                <input className="form-input" type="number" step="0.01" min="0" value={form.initial_reading} onChange={e => setForm({ ...form, initial_reading: parseFloat(e.target.value) })} required />
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-ghost" onClick={() => setShowAdd(false)}>Cancelar</button>
                <button type="submit" className="btn btn-primary" disabled={saving || !form.customer_id}>
                  {saving ? <Loader2 size={16} className="spinner" /> : 'Associar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {editing && (
        <div className="modal-overlay">
          <div className="modal">
            <div className="modal-header">
              <h2 className="modal-title">Editar Hidrômetro</h2>
              <button className="btn btn-ghost btn-icon" onClick={() => setEditing(null)}><X size={20} /></button>
            </div>
            <form onSubmit={handleEdit}>
              <div className="form-grid" style={{ marginBottom: 16 }}>
                <div className="form-group">
                  <label className="form-label">Código numérico</label>
                  <input className="form-input" value={editing.code} onChange={e => setEditing({ ...editing, code: e.target.value.replace(/\D/g, '') })} inputMode="numeric" />
                </div>
                <div className="form-group">
                  <label className="form-label">Última leitura base</label>
                  <input className="form-input" type="number" step="0.01" min="0" value={editing.last_reading_value} onChange={e => setEditing({ ...editing, last_reading_value: parseFloat(e.target.value) || 0 })} />
                </div>
              </div>
              <div className="form-grid" style={{ marginBottom: 16 }}>
                <div className="form-group">
                  <label className="form-label">Marca</label>
                  <input className="form-input" value={editing.brand || ''} onChange={e => setEditing({ ...editing, brand: e.target.value })} />
                </div>
                <div className="form-group">
                  <label className="form-label">Modelo</label>
                  <input className="form-input" value={editing.model || ''} onChange={e => setEditing({ ...editing, model: e.target.value })} />
                </div>
              </div>
              <div className="form-grid" style={{ marginBottom: 16 }}>
                <div className="form-group">
                  <label className="form-label">Dígitos vermelhos</label>
                  <select className="form-select" value={editing.red_digits || 3} onChange={e => setEditing({ ...editing, red_digits: Number(e.target.value) })}>
                    <option value={2}>2 dígitos vermelhos</option>
                    <option value={3}>3 dígitos vermelhos</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Dígitos pretos</label>
                  <input className="form-input" type="number" min={1} value={editing.black_digits || ''} onChange={e => setEditing({ ...editing, black_digits: e.target.value ? Number(e.target.value) : null })} placeholder="Opcional" />
                </div>
              </div>
              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Localização</label>
                <input className="form-input" value={editing.location_description || ''} onChange={e => setEditing({ ...editing, location_description: e.target.value })} />
              </div>
              <div className="form-group" style={{ marginBottom: 24 }}>
                <label className="form-label">Status</label>
                <select className="form-select" value={editing.is_active ? 'true' : 'false'} onChange={e => setEditing({ ...editing, is_active: e.target.value === 'true' })}>
                  <option value="true">Ativo</option>
                  <option value="false">Inativo</option>
                </select>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-ghost" onClick={() => setEditing(null)}>Cancelar</button>
                <button type="submit" className="btn btn-primary" disabled={saving}>
                  {saving ? <Loader2 size={16} className="spinner" /> : 'Salvar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
