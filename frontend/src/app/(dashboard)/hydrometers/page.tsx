'use client';

/* eslint-disable react-hooks/set-state-in-effect */

import { useEffect, useState, FormEvent } from 'react';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { useAppFeedback } from '@/components/AppFeedbackProvider';
import { Droplets, Plus, Search, Loader2, X } from 'lucide-react';

interface Customer {
  id: string;
  name: string;
  cpf_cnpj: string;
}

interface Hydrometer {
  id: string;
  code: string;
  customer_id: string;
  brand: string;
  model: string;
  location_description: string;
  last_reading_value: number;
  last_reading_date: string;
  is_active: boolean;
  installed_at: string;
  customer?: Customer;
}

export default function HydrometersPage() {
  const { notify } = useAppFeedback();
  const [items, setItems] = useState<Hydrometer[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState('');

  const [form, setForm] = useState({
    customer_id: '',
    code: '',
    brand: '',
    model: '',
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
        location_description: form.location_description || null,
        initial_reading: form.initial_reading,
      });
      setShowAdd(false);
      setForm({ customer_id: '', code: '', brand: '', model: '', location_description: '', initial_reading: 0 });
      load();
      notify('Hidrômetro associado', 'O medidor foi vinculado com sucesso.', 'success');
    } catch (err: unknown) {
      notify('Falha ao associar hidrômetro', err instanceof Error ? err.message : 'Erro ao criar hidrômetro.', 'error');
    } finally {
      setSaving(false);
    }
  };

  const filteredItems = items.filter(h =>
    h.code.toLowerCase().includes(search.toLowerCase()) ||
    h.customer?.name.toLowerCase().includes(search.toLowerCase())
  );

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
              <th>Local</th>
              <th>Última Leitura</th>
              <th>Status</th>
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
              <tr><td colSpan={5}><div className="empty-state"><Droplets /><p>Nenhum hidrômetro encontrado</p></div></td></tr>
            ) : filteredItems.map(h => (
              <tr key={h.id}>
                <td>
                  <div className="cell-primary" style={{ fontWeight: 800 }}>{h.code}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{h.customer?.name || 'Cliente desconhecido'}</div>
                </td>
                <td>{[h.brand, h.model].filter(Boolean).join(' ') || '—'}</td>
                <td>{h.location_description || '—'}</td>
                <td>
                  <span style={{ fontWeight: 600 }}>{h.last_reading_value.toFixed(2)} m³</span>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {h.last_reading_date ? new Date(h.last_reading_date).toLocaleDateString('pt-BR') : 'Sem leituras'}
                  </div>
                </td>
                <td><span className={`badge ${h.is_active ? 'active' : 'suspended'}`}>{h.is_active ? 'Ativo' : 'Inativo'}</span></td>
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
                <label className="form-label">Código do Hidrômetro (Letras)</label>
                <input
                  className="form-input"
                  placeholder="Ex: ZXCTRA (Deixe em branco para gerar aleatório)"
                  value={form.code}
                  onChange={e => setForm({ ...form, code: e.target.value.replace(/[^a-zA-Z]/g, '').toUpperCase() })}
                  maxLength={10}
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
    </>
  );
}
