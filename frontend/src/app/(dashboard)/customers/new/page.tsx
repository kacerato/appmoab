'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { ArrowLeft, Save, Loader2 } from 'lucide-react';

export default function NewCustomerPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState({
    name: '', cpf_cnpj: '', phone: '', email: '',
    address: '', number: 'S/N', complement: '', neighborhood: '',
    city: 'Moab', state: 'PA', zip_code: '',
    due_day: 10, has_hydrometer: true, notes: '',
  });

  const set = (field: string, value: string | number | boolean) =>
    setForm(f => ({ ...f, [field]: value }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      await api.post('/customers', form);
      router.push('/clientes');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Erro ao cadastrar');
    } finally { setLoading(false); }
  };

  return (
    <>
      <Header title="Novo Cliente" />
      <button className="btn btn-ghost btn-sm" onClick={() => router.back()} style={{ marginBottom: 20 }}>
        <ArrowLeft size={14} /> Voltar
      </button>

      {error && <div className="login-error" style={{ marginBottom: 16 }}>{error}</div>}

      <form onSubmit={handleSubmit}>
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-header"><span className="card-title">Dados Pessoais</span></div>
          <div className="form-grid">
            <div className="form-group">
              <label className="form-label">Nome Completo *</label>
              <input className="form-input" required value={form.name} onChange={e => set('name', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">CPF / CNPJ *</label>
              <input className="form-input" required value={form.cpf_cnpj} onChange={e => set('cpf_cnpj', e.target.value)} placeholder="000.000.000-00" />
            </div>
            <div className="form-group">
              <label className="form-label">Telefone</label>
              <input className="form-input" value={form.phone} onChange={e => set('phone', e.target.value)} placeholder="(00) 00000-0000" />
            </div>
            <div className="form-group">
              <label className="form-label">Email</label>
              <input className="form-input" type="email" value={form.email} onChange={e => set('email', e.target.value)} />
            </div>
          </div>
        </div>

        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-header"><span className="card-title">Endereço</span></div>
          <div className="form-grid">
            <div className="form-group" style={{ gridColumn: '1 / -1' }}>
              <label className="form-label">Logradouro *</label>
              <input className="form-input" required value={form.address} onChange={e => set('address', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Número</label>
              <input className="form-input" value={form.number} onChange={e => set('number', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Complemento</label>
              <input className="form-input" value={form.complement} onChange={e => set('complement', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Bairro *</label>
              <input className="form-input" required value={form.neighborhood} onChange={e => set('neighborhood', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Cidade *</label>
              <input className="form-input" required value={form.city} onChange={e => set('city', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">UF *</label>
              <input className="form-input" required maxLength={2} value={form.state} onChange={e => set('state', e.target.value.toUpperCase())} />
            </div>
            <div className="form-group">
              <label className="form-label">CEP *</label>
              <input className="form-input" required value={form.zip_code} onChange={e => set('zip_code', e.target.value)} placeholder="00000-000" />
            </div>
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
                <option value="true">Com hidrômetro (medido)</option>
                <option value="false">Sem hidrômetro (taxa fixa R$100)</option>
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
          <button type="submit" className="btn btn-primary" disabled={loading}>
            {loading ? <><Loader2 size={16} className="spinner" /> Salvando...</> : <><Save size={16} /> Cadastrar Cliente</>}
          </button>
        </div>
      </form>
    </>
  );
}
