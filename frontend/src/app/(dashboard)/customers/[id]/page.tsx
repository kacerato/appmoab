'use client';

import { useEffect, useMemo, useState, use, FormEvent, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import Header from '@/components/Header';
import { useAppFeedback } from '@/components/AppFeedbackProvider';
import { api } from '@/lib/api';
import { fileToDataUrl } from '@/lib/file-base64';
import { ArrowLeft, Calendar, Droplets, Edit2, FileText, Loader2, MapPin, Plus, Trash2, Upload, X } from 'lucide-react';

interface CustomerAttachment {
  id: string;
  original_name: string;
  mime_type: string;
  reference_month: string | null;
  notes: string | null;
  download_url: string;
  created_at: string;
}

interface Customer {
  id: string;
  name: string;
  cpf_cnpj: string;
  phone: string;
  email: string;
  address: string;
  number: string;
  complement: string;
  neighborhood: string;
  city: string;
  state: string;
  zip_code: string;
  due_day: number;
  has_hydrometer: boolean;
  status: string;
  notes: string;
  created_at: string;
  hydrometers: Hydrometer[];
  attachments: CustomerAttachment[];
  total_invoices: number;
  total_pending: number;
  total_overdue: number;
  billing_status: string;
  billing_status_label: string;
  days_until_due: number | null;
}

interface Hydrometer {
  id: string;
  code: string;
  last_reading_value: number;
  last_reading_date: string | null;
  red_digits: number | null;
  black_digits: number | null;
  is_active: boolean;
}

interface Invoice {
  id: string;
  amount: number;
  due_date: string;
  status: string;
  reference_month: string;
  consumption_m3: number;
}

function fmt(value: number) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);
}

function parseMeterReadingInput(input: string, redDigits: number) {
  const trimmed = input.trim().replace(',', '.');
  if (!trimmed) return null;

  if (trimmed.includes('.')) {
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : null;
  }

  const digits = trimmed.replace(/\D/g, '');
  if (!digits) return null;

  const rawValue = Number(digits);
  if (!Number.isFinite(rawValue)) return null;

  return redDigits > 0 ? rawValue / (10 ** redDigits) : rawValue;
}

function formatM3(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '--';
  return value.toLocaleString('pt-BR', {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  });
}

export default function CustomerDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { confirm, notify } = useAppFeedback();
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [invoices, setInvoices] = useState<Invoice[]>([]);
  const [loading, setLoading] = useState(true);
  const [showInvoiceModal, setShowInvoiceModal] = useState(false);
  const [showAttachmentModal, setShowAttachmentModal] = useState(false);
  const [savingInvoice, setSavingInvoice] = useState(false);
  const [savingAttachment, setSavingAttachment] = useState(false);
  const [adjustingHydrometerId, setAdjustingHydrometerId] = useState<string | null>(null);
  const [adjustingHydrometerValue, setAdjustingHydrometerValue] = useState('');
  const [savingHydrometer, setSavingHydrometer] = useState(false);

  const [invoiceForm, setInvoiceForm] = useState({
    amount: '',
    reference_month: new Date().toISOString().slice(0, 7),
    due_date: new Date().toISOString().slice(0, 10),
    consumption_m3: '',
    auto_amount: false,
  });
  const [attachmentForm, setAttachmentForm] = useState({
    reference_month: new Date().toISOString().slice(0, 7),
    notes: '',
    file: null as File | null,
  });

  const consumptionValue = useMemo(() => parseFloat(invoiceForm.consumption_m3 || '0'), [invoiceForm.consumption_m3]);
  const adjustingHydrometer = useMemo(
    () => customer?.hydrometers.find(hydrometer => hydrometer.id === adjustingHydrometerId) || null,
    [adjustingHydrometerId, customer],
  );
  const adjustingRedDigits = adjustingHydrometer?.red_digits || 3;
  const adjustedBaseValue = useMemo(
    () => parseMeterReadingInput(adjustingHydrometerValue, adjustingRedDigits),
    [adjustingHydrometerValue, adjustingRedDigits],
  );

  const load = useCallback(() => {
    Promise.all([
      api.get<Customer>(`/customers/${id}`),
      api.get<{ items: Invoice[] }>(`/invoices?customer_id=${id}&per_page=10`),
    ])
      .then(([c, inv]) => {
        setCustomer(c);
        setInvoices(inv.items);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const handleDelete = async () => {
    const confirmed = await confirm('Remover cliente', 'Deseja realmente desligar ou remover este cliente?', {
      confirmLabel: 'Remover',
    });
    if (!confirmed) return;
    try {
      await api.delete(`/customers/${id}`);
      notify('Cliente removido', 'O cadastro foi encerrado com sucesso.', 'success');
      router.push('/clientes');
    } catch (err: unknown) {
      notify('Falha ao excluir cliente', err instanceof Error ? err.message : 'Erro ao excluir.', 'error');
    }
  };

  const handleCreateInvoice = async (e: FormEvent) => {
    e.preventDefault();
    setSavingInvoice(true);
    try {
      await api.post('/invoices/manual', {
        customer_id: id,
        amount: parseFloat(invoiceForm.amount),
        reference_month: invoiceForm.reference_month,
        due_date: invoiceForm.due_date,
        consumption_m3: consumptionValue || 0,
      });
      setShowInvoiceModal(false);
      load();
      notify('Cobranca avulsa criada', 'A nova fatura foi gerada para o cliente.', 'success');
    } catch (err: unknown) {
      notify('Falha ao gerar cobranca', err instanceof Error ? err.message : 'Erro ao gerar fatura avulsa.', 'error');
    } finally {
      setSavingInvoice(false);
    }
  };

  const handleLegacyInvoiceUpload = async (e: FormEvent) => {
    e.preventDefault();
    if (!attachmentForm.file) {
      notify('Selecione um arquivo', 'Escolha o boleto antigo que deseja anexar.', 'warning');
      return;
    }

    setSavingAttachment(true);
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
      setShowAttachmentModal(false);
      load();
      notify('Boleto antigo anexado', 'O documento foi salvo no historico do cliente.', 'success');
    } catch (err: unknown) {
      notify('Falha ao anexar boleto', err instanceof Error ? err.message : 'Nao foi possivel anexar o boleto antigo.', 'error');
    } finally {
      setSavingAttachment(false);
    }
  };

  const handleAttachmentDelete = async (attachment: CustomerAttachment) => {
    const confirmed = await confirm('Remover anexo', `Deseja remover "${attachment.original_name}" do historico do cliente?`, {
      confirmLabel: 'Remover',
    });
    if (!confirmed) return;

    try {
      await api.delete(`/customers/${id}/attachments/${attachment.id}`);
      load();
      notify('Anexo removido', 'O documento antigo foi removido do historico.', 'success');
    } catch (err: unknown) {
      notify('Falha ao remover anexo', err instanceof Error ? err.message : 'Nao foi possivel remover o anexo.', 'error');
    }
  };

  const openHydrometerAdjust = (hydrometer: Hydrometer) => {
    setAdjustingHydrometerId(hydrometer.id);
    setAdjustingHydrometerValue(String(hydrometer.last_reading_value));
  };

  const handleHydrometerAdjust = async (e: FormEvent) => {
    e.preventDefault();
    if (!adjustingHydrometerId) return;

    setSavingHydrometer(true);
    try {
      if (adjustedBaseValue === null) {
        notify('Leitura inválida', 'Informe a leitura completa do visor ou o valor em m³.', 'warning');
        return;
      }
      await api.patch(`/hydrometers/${adjustingHydrometerId}`, {
        last_reading_value: adjustedBaseValue,
      });
      setAdjustingHydrometerId(null);
      setAdjustingHydrometerValue('');
      load();
      notify('Leitura-base atualizada', 'O ponto de partida do hidrometro foi ajustado com sucesso.', 'success');
    } catch (err: unknown) {
      notify('Falha ao ajustar leitura-base', err instanceof Error ? err.message : 'Nao foi possivel atualizar a leitura-base.', 'error');
    } finally {
      setSavingHydrometer(false);
    }
  };

  useEffect(() => {
    if (!invoiceForm.auto_amount || !consumptionValue || Number.isNaN(consumptionValue)) return;
    let active = true;
    api.get<{ final_amount: number }>(`/tariffs/simulate/${consumptionValue}`)
      .then(res => {
        if (active) {
          setInvoiceForm(current => ({ ...current, amount: res.final_amount.toFixed(2) }));
        }
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [invoiceForm.auto_amount, consumptionValue]);

  if (loading || !customer) {
    return <div className="loading-page"><div className="spinner" style={{ width: 32, height: 32 }} /></div>;
  }

  return (
    <>
      <Header
        title={customer.name}
        subtitle={`CPF/CNPJ: ${customer.cpf_cnpj}`}
        actions={(
          <div style={{ display: 'flex', gap: 10 }}>
            <button className="btn btn-secondary btn-sm" onClick={() => router.push(`/clientes/${id}/editar`)}>
              <Edit2 size={14} /> Editar
            </button>
            <button className="btn btn-danger btn-sm" onClick={handleDelete}>
              <Trash2 size={14} /> Excluir
            </button>
          </div>
        )}
      />

      <button className="btn btn-ghost btn-sm" onClick={() => router.push('/clientes')} style={{ marginBottom: 20 }}>
        <ArrowLeft size={14} /> Voltar
      </button>

      <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(4, 1fr)' }}>
        <div className="kpi-card blue">
          <div className="kpi-label">Status</div>
          <span className={`badge ${customer.status}`}>{customer.status === 'active' ? 'Ativo' : customer.status === 'suspended' ? 'Suspenso' : 'Desligado'}</span>
        </div>
        <div className="kpi-card cyan">
          <div className="kpi-label">Tipo</div>
          <div className="kpi-value" style={{ fontSize: 18 }}>{customer.has_hydrometer ? 'Medido' : 'Fixo'}</div>
        </div>
        <div className="kpi-card orange">
          <div className="kpi-label">Vencimento</div>
          <div className="kpi-value" style={{ fontSize: 18, color: billingColor(customer.billing_status) }}>{customer.billing_status_label}</div>
        </div>
        <div className="kpi-card red">
          <div className="kpi-label">Em atraso</div>
          <div className="kpi-value" style={{ fontSize: 20, color: 'var(--danger)' }}>{fmt(customer.total_overdue)}</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
        <div className="card">
          <div className="card-header"><span className="card-title">Informacoes</span></div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12, fontSize: 13 }}>
            <Info icon={<MapPin size={14} />} label="Endereco" value={`${customer.address}, ${customer.number} - ${customer.neighborhood}, ${customer.city}/${customer.state}`} />
            <Info icon={<Calendar size={14} />} label="Dia de vencimento" value={`Dia ${customer.due_day} de cada mes`} />
            {customer.phone && <Info icon={<span>📱</span>} label="Telefone" value={customer.phone} />}
            {customer.email && <Info icon={<span>✉️</span>} label="Email" value={customer.email} />}
            {customer.notes && <Info icon={<span>📝</span>} label="Observacoes" value={customer.notes} />}
          </div>
        </div>

        <div className="card">
          <div className="card-header"><span className="card-title">Hidrometros</span></div>
          {customer.hydrometers.length === 0 ? (
            <div className="empty-state" style={{ padding: 32 }}><p>{customer.has_hydrometer ? 'Nenhum hidrometro cadastrado' : 'Cliente sem hidrometro'}</p></div>
          ) : customer.hydrometers.map(hydrometer => (
            <div key={hydrometer.id} style={{ padding: '12px 0', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', gap: 12 }}>
              <div className="kpi-icon cyan" style={{ width: 36, height: 36 }}><Droplets size={16} /></div>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 700, fontSize: 14 }}>{hydrometer.code}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                  Base atual: {formatM3(hydrometer.last_reading_value)} m³
                  {hydrometer.last_reading_date && ` • ${new Date(hydrometer.last_reading_date).toLocaleDateString('pt-BR')}`}
                </div>
              </div>
              <button className="btn btn-secondary btn-sm" onClick={() => openHydrometerAdjust(hydrometer)}>
                Ajustar base
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="card" style={{ marginBottom: 24 }}>
        <div className="card-header">
          <div>
            <span className="card-title">Boletos antigos do cliente</span>
            <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>{customer.attachments.length} anexo(s)</span>
          </div>
          <button className="btn btn-primary btn-sm" onClick={() => setShowAttachmentModal(true)}>
            <Upload size={14} /> Anexar boleto antigo
          </button>
        </div>
        {!customer.attachments.length ? (
          <div className="empty-state" style={{ padding: 24 }}><p>Nenhum boleto antigo anexado ainda.</p></div>
        ) : (
          <div style={{ display: 'grid', gap: 10 }}>
            {customer.attachments.map(attachment => (
              <div key={attachment.id} className="card" style={{ padding: 14, marginBottom: 0 }}>
                <div style={{ display: 'flex', alignItems: 'start', justifyContent: 'space-between', gap: 14 }}>
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 700 }}>
                      <FileText size={14} />
                      <span>{attachment.original_name}</span>
                    </div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>
                      {attachment.reference_month ? `Referencia ${attachment.reference_month}` : 'Sem referencia informada'}
                      {' • '}
                      {new Date(attachment.created_at).toLocaleDateString('pt-BR')}
                    </div>
                    {attachment.notes && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 6 }}>{attachment.notes}</div>}
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <a className="btn btn-secondary btn-sm" href={`${process.env.NEXT_PUBLIC_API_URL?.replace(/\/api$/, '') || 'http://localhost:8000'}${attachment.download_url}`} target="_blank" rel="noreferrer">
                      Abrir
                    </a>
                    <button className="btn btn-danger btn-sm" onClick={() => handleAttachmentDelete(attachment)}>
                      Remover
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <div className="card-header">
          <div>
            <span className="card-title">Ultimas faturas</span>
            <span style={{ fontSize: 12, color: 'var(--text-muted)', marginLeft: 8 }}>{customer.total_invoices} total</span>
          </div>
          <button className="btn btn-primary btn-sm" onClick={() => setShowInvoiceModal(true)}>
            <Plus size={14} /> Cobranca avulsa
          </button>
        </div>
        <div className="table-wrapper" style={{ border: 'none' }}>
          <table className="data-table">
            <thead><tr><th>Referencia</th><th>Consumo</th><th>Valor</th><th>Vencimento</th><th>Status</th></tr></thead>
            <tbody>
              {invoices.length === 0 ? (
                <tr><td colSpan={5}><div className="empty-state" style={{ padding: 24 }}><p>Nenhuma fatura</p></div></td></tr>
              ) : invoices.map(inv => (
                <tr key={inv.id} onClick={() => router.push(`/faturas/${inv.id}`)} style={{ cursor: 'pointer' }}>
                  <td className="cell-primary">{inv.reference_month}</td>
                  <td>{inv.consumption_m3 > 0 ? `${inv.consumption_m3.toFixed(2)} m³` : 'Fixo / Avulso'}</td>
                  <td style={{ fontWeight: 600 }}>{fmt(inv.amount)}</td>
                  <td>{new Date(inv.due_date).toLocaleDateString('pt-BR')}</td>
                  <td><span className={`badge ${inv.status}`}>{statusLabel(inv.status)}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {showInvoiceModal && (
        <div className="modal-overlay">
          <div className="modal" style={{ maxWidth: 400 }}>
            <div className="modal-header">
              <h2 className="modal-title">Gerar boleto / fatura avulsa</h2>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowInvoiceModal(false)}><X size={20} /></button>
            </div>
            <form onSubmit={handleCreateInvoice}>
              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Valor (R$)</label>
                <input className="form-input" type="number" step="0.01" min="0.01" value={invoiceForm.amount} onChange={e => setInvoiceForm({ ...invoiceForm, amount: e.target.value })} required />
              </div>
              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Consumo associado (m³)</label>
                <input className="form-input" type="number" step="0.001" min="0" value={invoiceForm.consumption_m3} onChange={e => setInvoiceForm({ ...invoiceForm, consumption_m3: e.target.value })} placeholder="Opcional" />
                <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
                  <input type="checkbox" checked={invoiceForm.auto_amount} onChange={e => setInvoiceForm({ ...invoiceForm, auto_amount: e.target.checked })} />
                  Calcular valor automaticamente pela tabela quando houver consumo
                </label>
              </div>
              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Mes de referencia</label>
                <input className="form-input" type="month" value={invoiceForm.reference_month} onChange={e => setInvoiceForm({ ...invoiceForm, reference_month: e.target.value })} required />
              </div>
              <div className="form-group" style={{ marginBottom: 24 }}>
                <label className="form-label">Data de vencimento</label>
                <input className="form-input" type="date" value={invoiceForm.due_date} onChange={e => setInvoiceForm({ ...invoiceForm, due_date: e.target.value })} required />
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-ghost" onClick={() => setShowInvoiceModal(false)}>Cancelar</button>
                <button type="submit" className="btn btn-primary" disabled={savingInvoice || !invoiceForm.amount}>
                  {savingInvoice ? <Loader2 size={16} className="spinner" /> : 'Gerar boleto'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {showAttachmentModal && (
        <div className="modal-overlay">
          <div className="modal" style={{ maxWidth: 430 }}>
            <div className="modal-header">
              <h2 className="modal-title">Anexar boleto antigo</h2>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowAttachmentModal(false)}><X size={20} /></button>
            </div>
            <form onSubmit={handleLegacyInvoiceUpload}>
              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Arquivo</label>
                <input className="form-input" type="file" accept=".pdf,image/*" onChange={e => setAttachmentForm(current => ({ ...current, file: e.target.files?.[0] || null }))} required />
              </div>
              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Mes de referencia</label>
                <input className="form-input" type="month" value={attachmentForm.reference_month} onChange={e => setAttachmentForm(current => ({ ...current, reference_month: e.target.value }))} />
              </div>
              <div className="form-group" style={{ marginBottom: 24 }}>
                <label className="form-label">Observacoes</label>
                <textarea className="form-textarea" value={attachmentForm.notes} onChange={e => setAttachmentForm(current => ({ ...current, notes: e.target.value }))} />
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-ghost" onClick={() => setShowAttachmentModal(false)}>Cancelar</button>
                <button type="submit" className="btn btn-primary" disabled={savingAttachment}>
                  {savingAttachment ? <Loader2 size={16} className="spinner" /> : 'Anexar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {adjustingHydrometerId && (
        <div className="modal-overlay">
          <div className="modal" style={{ maxWidth: 380 }}>
            <div className="modal-header">
              <h2 className="modal-title">Ajustar leitura-base</h2>
              <button className="btn btn-ghost btn-icon" onClick={() => setAdjustingHydrometerId(null)}><X size={20} /></button>
            </div>
            <form onSubmit={handleHydrometerAdjust}>
              <div className="form-group" style={{ marginBottom: 24 }}>
                <label className="form-label">Leitura atual do hidrômetro</label>
                <input
                  className="form-input"
                  type="text"
                  inputMode="decimal"
                  value={adjustingHydrometerValue}
                  onChange={e => setAdjustingHydrometerValue(e.target.value)}
                  placeholder="Ex: 0090600"
                  required
                />
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 8, lineHeight: 1.5 }}>
                  Formato cadastrado: {adjustingRedDigits} vermelhos
                  {adjustingHydrometer?.black_digits ? ` · ${adjustingHydrometer.black_digits} pretos` : ''}. Interpretado como {formatM3(adjustedBaseValue)} m³.
                </div>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-ghost" onClick={() => setAdjustingHydrometerId(null)}>Cancelar</button>
                <button type="submit" className="btn btn-primary" disabled={savingHydrometer}>
                  {savingHydrometer ? <Loader2 size={16} className="spinner" /> : 'Salvar base'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}

function Info({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
      <span style={{ color: 'var(--text-muted)', marginTop: 2 }}>{icon}</span>
      <div>
        <div style={{ color: 'var(--text-muted)', fontSize: 11, marginBottom: 2 }}>{label}</div>
        <div>{value}</div>
      </div>
    </div>
  );
}

function statusLabel(status: string) {
  const map: Record<string, string> = { pending: 'Pendente', sent: 'Enviado', paid: 'Pago', overdue: 'Vencido', cancelled: 'Cancelado' };
  return map[status] || status;
}

function billingColor(status: string) {
  if (status === 'overdue' || status === 'due_today') return 'var(--danger)';
  if (status === 'near_due') return 'var(--warning)';
  return 'var(--success)';
}
