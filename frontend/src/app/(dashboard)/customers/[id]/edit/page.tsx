'use client';

import { useEffect, useState, use, FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import Header from '@/components/Header';
import { api } from '@/lib/api';
import { fileToDataUrl } from '@/lib/file-base64';
import { ArrowLeft, Loader2, Save, Trash2, Upload } from 'lucide-react';

interface Attachment {
  id: string;
  original_name: string;
  reference_month: string | null;
  notes: string | null;
  download_url: string;
}

export default function EditCustomerPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploadingAttachment, setUploadingAttachment] = useState(false);
  const [attachmentForm, setAttachmentForm] = useState({
    reference_month: new Date().toISOString().slice(0, 7),
    notes: '',
    file: null as File | null,
  });
  const [form, setForm] = useState({
    name: '', phone: '', email: '', address: '', number: '', complement: '',
    neighborhood: '', city: '', state: '', zip_code: '', due_day: 10,
    has_hydrometer: true, status: 'active', notes: '',
  });

  useEffect(() => {
    api.get<any>(`/customers/${id}`)
      .then(customer => {
        setForm({
          name: customer.name, phone: customer.phone || '', email: customer.email || '',
          address: customer.address, number: customer.number, complement: customer.complement || '',
          neighborhood: customer.neighborhood, city: customer.city, state: customer.state,
          zip_code: customer.zip_code, due_day: customer.due_day, has_hydrometer: customer.has_hydrometer,
          status: customer.status, notes: customer.notes || '',
        });
        setAttachments(customer.attachments || []);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  const set = (field: string, value: string | number | boolean) =>
    setForm(current => ({ ...current, [field]: value }));

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      await api.patch(`/customers/${id}`, form);
      router.push(`/clientes/${id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar');
    } finally {
      setSaving(false);
    }
  };

  const refreshAttachments = async () => {
    const customer = await api.get<any>(`/customers/${id}`);
    setAttachments(customer.attachments || []);
  };

  const handleAttachmentUpload = async (e: FormEvent) => {
    e.preventDefault();
    if (!attachmentForm.file) return;

    setUploadingAttachment(true);
    try {
      const fileBase64 = await fileToDataUrl(attachmentForm.file);
      await api.post(`/customers/${id}/attachments`, {
        original_name: attachmentForm.file.name,
        mime_type: attachmentForm.file.type || 'application/octet-stream',
        file_base64: fileBase64,
        reference_month: attachmentForm.reference_month || null,
        notes: attachmentForm.notes || null,
      });
      setAttachmentForm({
        reference_month: new Date().toISOString().slice(0, 7),
        notes: '',
        file: null,
      });
      await refreshAttachments();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Erro ao anexar boleto antigo');
    } finally {
      setUploadingAttachment(false);
    }
  };

  const handleAttachmentDelete = async (attachmentId: string) => {
    try {
      await api.delete(`/customers/${id}/attachments/${attachmentId}`);
      await refreshAttachments();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Erro ao remover anexo');
    }
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
          <div className="card-header"><span className="card-title">Endereco</span></div>
          <div className="form-grid">
            <div className="form-group" style={{ gridColumn: '1 / -1' }}>
              <label className="form-label">Logradouro</label>
              <input className="form-input" value={form.address} onChange={e => set('address', e.target.value)} required />
            </div>
            <div className="form-group"><label className="form-label">Numero</label><input className="form-input" value={form.number} onChange={e => set('number', e.target.value)} /></div>
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
              <input className="form-input" type="number" min={1} max={28} value={form.due_day} onChange={e => set('due_day', parseInt(e.target.value, 10) || 10)} />
            </div>
            <div className="form-group">
              <label className="form-label">Tipo</label>
              <select className="form-select" value={form.has_hydrometer ? 'true' : 'false'} onChange={e => set('has_hydrometer', e.target.value === 'true')}>
                <option value="true">Com hidrometro</option>
                <option value="false">Sem hidrometro (fixo)</option>
              </select>
            </div>
          </div>
          <div className="form-group" style={{ marginTop: 16 }}>
            <label className="form-label">Observacoes</label>
            <textarea className="form-textarea" value={form.notes} onChange={e => set('notes', e.target.value)} />
          </div>
        </div>

        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-header"><span className="card-title">Boletos Antigos</span></div>
          <form onSubmit={handleAttachmentUpload} className="form-grid" style={{ gridTemplateColumns: '1.2fr 0.8fr 1fr auto', marginBottom: 18 }}>
            <input className="form-input" type="file" accept=".pdf,image/*" onChange={e => setAttachmentForm(current => ({ ...current, file: e.target.files?.[0] || null }))} />
            <input className="form-input" type="month" value={attachmentForm.reference_month} onChange={e => setAttachmentForm(current => ({ ...current, reference_month: e.target.value }))} />
            <input className="form-input" placeholder="Observacoes" value={attachmentForm.notes} onChange={e => setAttachmentForm(current => ({ ...current, notes: e.target.value }))} />
            <button className="btn btn-primary btn-sm" type="submit" disabled={uploadingAttachment || !attachmentForm.file}>
              {uploadingAttachment ? <Loader2 size={14} className="spinner" /> : <Upload size={14} />} Anexar
            </button>
          </form>

          {!attachments.length ? (
            <div className="empty-state" style={{ padding: 20 }}><p>Nenhum boleto antigo anexado.</p></div>
          ) : (
            <div style={{ display: 'grid', gap: 10 }}>
              {attachments.map(attachment => (
                <div key={attachment.id} className="card" style={{ marginBottom: 0, padding: 14 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                    <div>
                      <div style={{ fontWeight: 700 }}>{attachment.original_name}</div>
                      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
                        {attachment.reference_month || 'Sem referencia'} {attachment.notes ? `• ${attachment.notes}` : ''}
                      </div>
                    </div>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <a className="btn btn-secondary btn-sm" href={`${process.env.NEXT_PUBLIC_API_URL?.replace(/\/api$/, '') || 'http://localhost:8000'}${attachment.download_url}`} target="_blank" rel="noreferrer">
                        Abrir
                      </a>
                      <button type="button" className="btn btn-danger btn-sm" onClick={() => handleAttachmentDelete(attachment.id)}>
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button type="button" className="btn btn-secondary" onClick={() => router.back()}>Cancelar</button>
          <button type="submit" className="btn btn-primary" disabled={saving}>
            {saving ? <><Loader2 size={16} className="spinner" /> Salvando...</> : <><Save size={16} /> Salvar Alteracoes</>}
          </button>
        </div>
      </form>
    </>
  );
}
