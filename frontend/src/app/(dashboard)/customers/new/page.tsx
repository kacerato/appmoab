'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import Header from '@/components/Header';
import { api } from '@/lib/api';
import { fileToDataUrl } from '@/lib/file-base64';
import { ArrowLeft, Loader2, Save, Trash2, Upload } from 'lucide-react';

interface PendingAttachment {
  id: string;
  file: File;
  reference_month: string;
  notes: string;
}

export default function NewCustomerPage() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [pendingAttachments, setPendingAttachments] = useState<PendingAttachment[]>([]);
  const [attachmentDraft, setAttachmentDraft] = useState({
    file: null as File | null,
    reference_month: new Date().toISOString().slice(0, 7),
    notes: '',
  });
  const [form, setForm] = useState({
    name: '', cpf_cnpj: '', phone: '', email: '',
    address: '', number: 'S/N', complement: '', neighborhood: '',
    city: 'Moab', state: 'PA', zip_code: '',
    due_day: 10, has_hydrometer: true, notes: '',
    hydrometer_initial_reading: 0,
    hydrometer_red_digits: 3,
    hydrometer_black_digits: '',
    hydrometer_brand: '',
    hydrometer_model: '',
    hydrometer_location_description: '',
  });

  const set = (field: string, value: string | number | boolean) =>
    setForm(current => ({ ...current, [field]: value }));

  const queueAttachment = () => {
    if (!attachmentDraft.file) return;
    setPendingAttachments(current => [
      ...current,
      {
        id: crypto.randomUUID(),
        file: attachmentDraft.file!,
        reference_month: attachmentDraft.reference_month,
        notes: attachmentDraft.notes,
      },
    ]);
    setAttachmentDraft({
      file: null,
      reference_month: new Date().toISOString().slice(0, 7),
      notes: '',
    });
  };

  const removePendingAttachment = (id: string) => {
    setPendingAttachments(current => current.filter(item => item.id !== id));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');
    try {
      const customer = await api.post<{ id: string }>('/customers', {
        ...form,
        hydrometer_black_digits: form.hydrometer_black_digits === '' ? null : Number(form.hydrometer_black_digits),
      });

      for (const attachment of pendingAttachments) {
        const fileBase64 = await fileToDataUrl(attachment.file);
        await api.post(`/customers/${customer.id}/attachments`, {
          original_name: attachment.file.name,
          mime_type: attachment.file.type || 'application/octet-stream',
          file_base64: fileBase64,
          reference_month: attachment.reference_month || null,
          notes: attachment.notes || null,
        });
      }

      router.push(`/clientes/${customer.id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Erro ao cadastrar');
    } finally {
      setLoading(false);
    }
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
          <div className="card-header"><span className="card-title">Endereco</span></div>
          <div className="form-grid">
            <div className="form-group" style={{ gridColumn: '1 / -1' }}>
              <label className="form-label">Logradouro *</label>
              <input className="form-input" required value={form.address} onChange={e => set('address', e.target.value)} />
            </div>
            <div className="form-group">
              <label className="form-label">Numero</label>
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
              <input className="form-input" type="number" min={1} max={28} value={form.due_day} onChange={e => set('due_day', parseInt(e.target.value, 10) || 10)} />
            </div>
            <div className="form-group">
              <label className="form-label">Tipo</label>
              <select className="form-select" value={form.has_hydrometer ? 'true' : 'false'} onChange={e => set('has_hydrometer', e.target.value === 'true')}>
                <option value="true">Com hidrometro (medido)</option>
                <option value="false">Sem hidrometro (taxa fixa R$100)</option>
              </select>
            </div>
          </div>
          <div className="form-group" style={{ marginTop: 16 }}>
            <label className="form-label">Observacoes</label>
            <textarea className="form-textarea" value={form.notes} onChange={e => set('notes', e.target.value)} />
          </div>
        </div>

        {form.has_hydrometer && (
          <div className="card" style={{ marginBottom: 20 }}>
            <div className="card-header"><span className="card-title">Hidrômetro inicial</span></div>
            <div className="form-grid">
              <div className="form-group">
                <label className="form-label">Última leitura cadastrada</label>
                <input className="form-input" type="number" step="0.001" min="0" value={form.hydrometer_initial_reading} onChange={e => set('hydrometer_initial_reading', parseFloat(e.target.value) || 0)} />
              </div>
              <div className="form-group">
                <label className="form-label">Dígitos vermelhos</label>
                <select className="form-select" value={form.hydrometer_red_digits} onChange={e => set('hydrometer_red_digits', Number(e.target.value))}>
                  <option value={2}>2 dígitos vermelhos</option>
                  <option value={3}>3 dígitos vermelhos</option>
                </select>
              </div>
              <div className="form-group">
                <label className="form-label">Dígitos pretos</label>
                <input className="form-input" type="number" min={1} value={form.hydrometer_black_digits} onChange={e => set('hydrometer_black_digits', e.target.value)} placeholder="Opcional" />
              </div>
              <div className="form-group">
                <label className="form-label">Marca</label>
                <input className="form-input" value={form.hydrometer_brand} onChange={e => set('hydrometer_brand', e.target.value)} placeholder="Ex: LAO, Elster" />
              </div>
              <div className="form-group">
                <label className="form-label">Modelo</label>
                <input className="form-input" value={form.hydrometer_model} onChange={e => set('hydrometer_model', e.target.value)} />
              </div>
              <div className="form-group">
                <label className="form-label">Local do hidrômetro</label>
                <input className="form-input" value={form.hydrometer_location_description} onChange={e => set('hydrometer_location_description', e.target.value)} placeholder="Ex: Muro frontal esquerdo" />
              </div>
            </div>
          </div>
        )}

        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-header"><span className="card-title">Boletos Antigos</span></div>
          <div className="form-grid" style={{ gridTemplateColumns: '1.2fr 0.8fr 1fr auto', marginBottom: 18 }}>
            <input className="form-input" type="file" accept=".pdf,image/*" onChange={e => setAttachmentDraft(current => ({ ...current, file: e.target.files?.[0] || null }))} />
            <input className="form-input" type="month" value={attachmentDraft.reference_month} onChange={e => setAttachmentDraft(current => ({ ...current, reference_month: e.target.value }))} />
            <input className="form-input" placeholder="Observacoes" value={attachmentDraft.notes} onChange={e => setAttachmentDraft(current => ({ ...current, notes: e.target.value }))} />
            <button type="button" className="btn btn-primary btn-sm" onClick={queueAttachment} disabled={!attachmentDraft.file}>
              <Upload size={14} /> Adicionar
            </button>
          </div>

          {!pendingAttachments.length ? (
            <div className="empty-state" style={{ padding: 20 }}><p>Nenhum boleto antigo na fila.</p></div>
          ) : (
            <div style={{ display: 'grid', gap: 10 }}>
              {pendingAttachments.map(attachment => (
                <div key={attachment.id} className="card" style={{ marginBottom: 0, padding: 14 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                    <div>
                      <div style={{ fontWeight: 700 }}>{attachment.file.name}</div>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                        {attachment.reference_month || 'Sem referencia'} {attachment.notes ? `• ${attachment.notes}` : ''}
                      </div>
                    </div>
                    <button type="button" className="btn btn-danger btn-sm" onClick={() => removePendingAttachment(attachment.id)}>
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
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
