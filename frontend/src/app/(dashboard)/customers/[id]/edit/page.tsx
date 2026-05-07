'use client';

import { useEffect, useState, use } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { ArrowLeft, Save, Loader2 } from 'lucide-react';

export default function EditCustomerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState({
    name: '', phone: '', email: '', address: '', number: '', complement: '',
    neighborhood: '', city: '', state: '', zip_code: '', due_day: 10,
    has_hydrometer: true, status: 'active', notes: '',
  });

  useEffect(() => {
    api.get<any>(`/customers/${id}`)
      .then(c => setForm({
        name: c.name, phone: c.phone || '', email: c.email || '',
        address: c.address, number: c.number, complement: c.complement || '',
        neighborhood: c.neighborhood, city: c.city, state: c.state,
        zip_code: c.zip_code, due_day: c.due_day, has_hydrometer: c.has_hydrometer,
        status: c.status, notes: c.notes || '',
      }))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  const set = (field: string, value: string | number | boolean) =>
    setForm(f => ({ ...f, [field]: value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      await api.patch(`/customers/${id}`, form);
      router.push(`/customers/${id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar');
    } finally { setSaving(false); }
  };

  if (loading) return <div className="loading-page"><div className="spinner" style={{ width: 32, height: 32 }} /></div>;

  return (
    <>
      <Header title="Editar Cliente" subtitle={form.name} />
      <button className="btn btn-ghost btn-sm" onClick={() => router.back()} style={{ marginBottom: 20 }}>
        <ArrowLeft size={14} /> Voltar
      </button>

      {error && <div className="login-error" style={{ marginBottom: 16 }}>{error}</div>}

      <form onSubmit={handleSubmit}>
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-header"><span className="card-title">Dados Pessoais</span></div>
          <div className="form-grid">
            <div className="form-group">
              <label className="form-label">Nome Completo</label>
              <input className="form-input" value={form.name} onChange={e => set('name', e.target.value)} required />
            </div>
            <div className="form-group">
              <label className="form-label">Telefone</label>
              <input className="form-input" value={form.phone} onChange={e => set('phone', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Email</label>
              <input className="form-input" type="email" value={form.email} onChange={e => set('email', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Status</label>
              <select className="form-select" value={form.status} onChange={e => set('status', e.target.value)}>
                <option value="active">Ativo</option>
                <option value="suspended">Suspenso</option>
                <option value="disconnected">Desligado</option>
              </select>
            </div>
          </div>
        </div>

        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-header"><span className="card-title">Endereço</span></div>
          <div className="form-grid">
            <div className="form-group" style={{ gridColumn: '1 / -1' }}>
              <label className="form-label">Logradouro</label>
              <input className="form-input" value={form.address} onChange={e => set('address', e.target.value)} required />
            </div>
            <div className="form-group"><label className="form-label">Número</label><input className="form-input" value={form.number} onChange={e => set('number', e.target.value)} /></div>
            <div className="form-group"><label className="form-label">Complemento</label><input className="form-input" value={form.complement} onChange={e => set('complement', e.target.value)} /></div>
            <div className="form-group"><label className="form-label">Bairro</label><input className="form-input" value={form.neighborhood} onChange={e => set('neighborhood', e.target.value)} required /></div>
            <div className="form-group"><label className="form-label">Cidade</label><input className="form-input" value={form.city} onChange={e => set('city', e.target.value)} required /></div>
            <div className="form-group"><label className="form-label">UF</label><input className="form-input" maxLength={2} value={form.state} onChange={e => set('state', e.target.value.toUpperCase())} required /></div>
            <div className="form-group"><label className="form-label">CEP</label><input className="form-input" value={form.zip_code} onChange={e => set('zip_code', e.target.value)} required /></div>
          </div>
        </div>

        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-header"><span className="card-title">Faturamento</span></div>
          <div className="form-grid">
            <div className="form-group">
              <label className="form-label">Dia de Vencimento</label>
              <input className="form-input" type="number" min={1} max={28} value={form.due_day} onChange={e => set('due_day', parseInt(e.target.value) || 10)} />
            </div>
            <div className="form-group">
              <label className="form-label">Tipo</label>
              <select className="form-select" value={form.has_hydrometer ? 'true' : 'false'} onChange={e => set('has_hydrometer', e.target.value === 'true')}>
                <option value="true">Com hidrômetro</option>
                <option value="false">Sem hidrômetro (fixo)</option>
              </select>
            </div>
          </div>
          <div className="form-group" style={{ marginTop: 16 }}>
            <label className="form-label">Observações</label>
            <textarea className="form-textarea" value={form.notes} onChange={e => set('notes', e.target.value)} />
          </div>
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button type="button" className="btn btn-secondary" onClick={() => router.back()}>Cancelar</button>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? <><Loader2 size={16} className="spinner" /> Salvando...</> : <><Save size={16} /> Salvar Alterações</>}
          </button>
        </div>
      </form>
    </>
  );
}
