'use client';

/* eslint-disable react-hooks/set-state-in-effect */

import { useEffect, useState, useCallback } from 'react';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { useAppFeedback } from '@/components/AppFeedbackProvider';
import { AlertTriangle, ClipboardCheck, Check, X, Camera, MapPin, Sparkles } from 'lucide-react';

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api').replace(/\/api$/, '');

interface Reading {
  id: string;
  current_value: number | null;
  previous_value: number;
  consumption: number | null;
  photo_url: string;
  photo_extracted_code: string | null;
  photo_extracted_value: number | null;
  ocr_confidence: number | null;
  latitude: number | null;
  longitude: number | null;
  location_accuracy_meters: number | null;
  distance_from_hydrometer_meters: number | null;
  location_status: string;
  validation_flags: Array<{ code: string; label: string; message: string; severity: 'info' | 'warning' | 'danger' | string }>;
  captured_at: string;
  status: string;
  rejection_reason: string;
  collaborator_name: string;
  hydrometer_code: string;
  customer_name: string;
  customer_id: string;
  is_installation: boolean;
  charge_type: string | null;
  review_adjustment_reason: string | null;
  vision_predicted_code: string | null;
  vision_predicted_value: number | null;
  vision_confidence: number | null;
  vision_decision: string | null;
  vision_digits: Array<{
    position?: number;
    value?: number | null;
    confidence?: number;
    current_digit?: number | null;
    next_digit?: number | null;
    transition_phase?: number | null;
    transitional?: boolean;
  }>;
  vision_alternatives: Array<string | number | { code?: string; value?: number }>;
  vision_quality: Record<string, unknown>;
  vision_flags: string[];
  vision_rectified_url: string | null;
  vision_original_url: string | null;
  vision_frame_urls: string[];
  vision_selected_frame_index: number | null;
  reference_month: string | null;
  reading_kind: string;
}

function alertTone(flags: Reading['validation_flags']) {
  if (flags.some(flag => flag.severity === 'danger')) return 'danger';
  if (flags.some(flag => flag.severity === 'warning')) return 'warning';
  return 'info';
}

function alertColors(severity: string) {
  if (severity === 'danger') {
    return { bg: 'rgba(220, 38, 38, 0.08)', border: 'rgba(220, 38, 38, 0.22)', color: 'var(--danger)' };
  }
  if (severity === 'warning') {
    return { bg: 'rgba(217, 119, 6, 0.08)', border: 'rgba(217, 119, 6, 0.22)', color: 'var(--warning)' };
  }
  return { bg: 'var(--accent-soft)', border: 'rgba(0, 119, 200, 0.18)', color: 'var(--accent)' };
}

interface ListRes {
  items: Reading[];
  total: number;
  page: number;
  per_page: number;
}

export default function ReadingsPage() {
  const { notify, prompt } = useAppFeedback();
  const [data, setData] = useState<ListRes | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('pending');
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [draftValues, setDraftValues] = useState<Record<string, string>>({});
  const [draftReasons, setDraftReasons] = useState<Record<string, string>>({});

  const load = useCallback(async (force = false, silent = false) => {
    if (!silent) setLoading(true);
    try {
      const res = await api.get<ListRes>(`/readings?status=${filter}&per_page=50`, { skipCache: force });
      setData(res);
      setDraftValues(current => {
        const next = { ...current };
        res.items.forEach(reading => {
          if (!(reading.id in next)) {
            const suggestion = reading.vision_predicted_value ?? reading.photo_extracted_value ?? reading.current_value;
            next[reading.id] = suggestion === null ? '' : String(suggestion).replace('.', ',');
          }
        });
        return next;
      });
    } catch (e) {
      console.error(e);
    } finally {
      if (!silent) setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    void load(false);
  }, [load]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        void load(true, true);
      }
    }, 5000);
    const handleFocus = () => void load(true, true);
    window.addEventListener('focus', handleFocus);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener('focus', handleFocus);
    };
  }, [load]);

  const approve = async (reading: Reading, confirmSuggestion = false) => {
    const suggestion = reading.vision_predicted_value ?? reading.photo_extracted_value;
    const rawValue = confirmSuggestion && suggestion !== null
      ? String(suggestion)
      : draftValues[reading.id] || '';
    const value = Number(rawValue.replace(',', '.'));
    if (!Number.isFinite(value) || value < 0) {
      notify('Leitura inválida', 'Informe a medição que aparece no visor antes de aprovar.', 'warning');
      return;
    }
    const adjusted = suggestion !== null && Math.abs(value - suggestion) > 0.0005;

    setActionLoading(reading.id);
    try {
      const result = await api.post<{ whatsapp_status?: string }>(`/readings/${reading.id}/approve`, {
        current_value: value,
        adjustment_reason: adjusted
          ? (draftReasons[reading.id]?.trim() || 'Valor ajustado manualmente no dashboard')
          : null,
      });
      setData(current => current ? {
        ...current,
        total: Math.max(0, current.total - 1),
        items: current.items.filter(item => item.id !== reading.id),
      } : current);
      notify(
        'Leitura confirmada',
        result.whatsapp_status === 'queued'
          ? 'Consumo e fatura gerados; o WhatsApp entrou na fila de envio.'
          : 'Consumo e fatura gerados com o valor confirmado.',
        'success',
      );
      void load(true, true);
    } catch (e) {
      notify('Falha ao aprovar leitura', e instanceof Error ? e.message : 'Erro ao aprovar leitura.', 'error');
    } finally {
      setActionLoading(null);
    }
  };

  const reject = async (id: string) => {
    const reason = await prompt('Rejeitar leitura', 'Informe o motivo da rejeição para registrar no histórico.', {
      confirmLabel: 'Rejeitar',
      placeholder: 'Ex: foto desfocada ou leitura inconsistente',
    });
    if (!reason) return;

    setActionLoading(id);
    try {
      await api.post(`/readings/${id}/reject`, { reason });
      setData(current => current ? {
        ...current,
        total: Math.max(0, current.total - 1),
        items: current.items.filter(item => item.id !== id),
      } : current);
      notify('Leitura rejeitada', 'O motivo foi salvo para revisão posterior.', 'warning');
      void load(true, true);
    } catch (e) {
      notify('Falha ao rejeitar leitura', e instanceof Error ? e.message : 'Erro ao rejeitar leitura.', 'error');
    } finally {
      setActionLoading(null);
    }
  };

  return (
    <>
      <Header title="Leituras" subtitle={`${data?.total || 0} registros`} />

      <div className="toolbar">
        {['pending', 'approved', 'rejected'].map(s => (
          <button
            key={s}
            className={`btn ${filter === s ? 'btn-primary' : 'btn-secondary'} btn-sm`}
            onClick={() => setFilter(s)}
          >
            {s === 'pending' ? 'Pendentes' : s === 'approved' ? 'Aprovadas' : 'Rejeitadas'}
            {s === 'pending' && data?.total ? ` (${data.total})` : ''}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="loading-page"><div className="spinner" style={{ width: 32, height: 32 }} /></div>
      ) : !data?.items.length ? (
        <div className="empty-state"><ClipboardCheck /><p>Nenhuma leitura {filter === 'pending' ? 'pendente' : filter === 'approved' ? 'aprovada' : 'rejeitada'}</p></div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(430px, 1fr))', gap: 16 }}>
          {data.items.map(r => (
            <div key={r.id} className="card" style={{ padding: 0, overflow: 'hidden', borderColor: alertTone(r.validation_flags || []) === 'danger' ? 'rgba(220, 38, 38, 0.28)' : undefined }}>
              <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 15 }}>{r.customer_name || 'Cliente'}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
                      <Camera size={11} /> {r.hydrometer_code || 'N/A'}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                    {r.is_installation && <span className="badge upcoming">Instalação</span>}
                    {r.reference_month && <span className="badge suspended">Ref. {r.reference_month.slice(5)}/{r.reference_month.slice(0, 4)}</span>}
                    <span className={`badge ${r.status}`}>{r.status === 'pending' ? 'Pendente' : r.status === 'approved' ? 'Aprovada' : 'Rejeitada'}</span>
                  </div>
                </div>

                {r.is_installation && (
                  <div style={{ marginTop: 10, padding: '8px 10px', borderRadius: 8, background: 'var(--accent-soft)', color: 'var(--accent)', fontSize: 12, fontWeight: 700 }}>
                    Primeira captura do hidrômetro. Ao aprovar, vira leitura-base e gera cobrança de instalação.
                  </div>
                )}

                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12, marginTop: 12 }}>
                  <div><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Anterior</div><div style={{ fontWeight: 600 }}>{r.previous_value.toFixed(2)}</div></div>
                  <div><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{r.status === 'pending' ? 'Sugestão OCR' : 'Confirmada'}</div><div style={{ fontWeight: 600 }}>{(r.status === 'pending' ? (r.vision_predicted_value ?? r.photo_extracted_value) : r.current_value)?.toFixed(3) ?? '—'}</div></div>
                  <div><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Consumo</div><div style={{ fontWeight: 700, color: 'var(--cyan)' }}>{r.consumption !== null ? `${r.consumption.toFixed(3)} m³` : 'Após confirmar'}</div></div>
                </div>

                {(r.vision_confidence ?? r.ocr_confidence) !== null && (
                  <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-muted)' }}>
                    OCR: {(((r.vision_confidence ?? r.ocr_confidence) || 0) * 100).toFixed(0)}% confiança
                    {r.vision_decision && ` • ${r.vision_decision === 'accepted' ? 'alta concordância' : r.vision_decision === 'recapture' ? 'captura fraca' : 'revisão necessária'}`}
                  </div>
                )}

                {!!r.vision_digits?.length && (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 12 }}>
                    {r.vision_digits.map((digit, index) => (
                      <div key={`${digit.position ?? index}-${index}`} style={{ minWidth: 38, padding: '7px 8px', textAlign: 'center', borderRadius: 8, background: digit.transitional ? 'var(--warning-soft)' : 'var(--blue-50)', border: `1px solid ${digit.transitional ? 'var(--warning)' : 'var(--border)'}` }}>
                        <div style={{ fontSize: 16, fontWeight: 900 }}>{digit.value ?? '—'}</div>
                        <div style={{ fontSize: 9, color: digit.transitional ? 'var(--warning)' : 'var(--text-muted)' }}>
                          {digit.transitional ? `${digit.current_digit}→${digit.next_digit}` : `${Math.round((digit.confidence || 0) * 100)}%`}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {!!r.vision_alternatives?.length && (
                  <div style={{ marginTop: 9, fontSize: 11, color: 'var(--text-muted)' }}>
                    Alternativas: {r.vision_alternatives.slice(0, 3).map(item => typeof item === 'object' ? (item.code ?? item.value ?? '—') : item).join(' • ')}
                  </div>
                )}

                {!!r.validation_flags?.length && (
                  <div style={{ display: 'grid', gap: 8, marginTop: 12 }}>
                    {r.validation_flags.map((flag, index) => {
                      const tone = alertColors(flag.severity);
                      return (
                        <div
                          key={`${flag.code}-${index}`}
                          style={{
                            display: 'grid',
                            gridTemplateColumns: '16px minmax(0, 1fr)',
                            gap: 8,
                            alignItems: 'start',
                            padding: '8px 10px',
                            borderRadius: 8,
                            background: tone.bg,
                            border: `1px solid ${tone.border}`,
                            color: tone.color,
                          }}
                        >
                          <AlertTriangle size={14} style={{ marginTop: 1 }} />
                          <div>
                            <div style={{ fontSize: 12, fontWeight: 800 }}>{flag.label}</div>
                            <div style={{ fontSize: 11.5, color: 'var(--text-secondary)', lineHeight: 1.4, marginTop: 2 }}>{flag.message}</div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              <div style={{ padding: '10px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12, color: 'var(--text-muted)' }}>
                <div>{new Date(r.captured_at).toLocaleString('pt-BR')}</div>
                <div>{r.collaborator_name}</div>
              </div>

              <div style={{ padding: '0 20px 14px', display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, max-content)) minmax(180px, 1fr)', gap: 12, alignItems: 'center' }}>
                <ReadingPhoto url={r.photo_url} label="Foto enviada" />
                {r.vision_original_url && r.vision_original_url !== r.photo_url && (
                  <ReadingPhoto url={r.vision_original_url} label="Frame analisado" />
                )}
                {r.vision_selected_frame_index !== null && r.vision_frame_urls?.[r.vision_selected_frame_index] && (
                  <ReadingPhoto url={r.vision_frame_urls[r.vision_selected_frame_index]} label={`Frame escolhido #${r.vision_selected_frame_index + 1}`} />
                )}
                {r.vision_rectified_url && <ReadingPhoto url={r.vision_rectified_url} label="Recorte do visor" />}
                <div style={{ display: 'grid', gap: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
                  <div><strong>Hora da foto:</strong> {new Date(r.captured_at).toLocaleString('pt-BR')}</div>
                  <div><strong>Localizacao:</strong> {r.latitude && r.longitude ? `${r.latitude.toFixed(6)}, ${r.longitude.toFixed(6)}` : 'Nao registrada'}</div>
                  {(r.distance_from_hydrometer_meters !== null || r.location_accuracy_meters !== null) && (
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                      {r.distance_from_hydrometer_meters !== null && (
                        <span className="badge suspended" style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                          <MapPin size={11} /> {r.distance_from_hydrometer_meters.toFixed(0)}m da base
                        </span>
                      )}
                      {r.location_accuracy_meters !== null && (
                        <span className="badge suspended">GPS {r.location_accuracy_meters.toFixed(0)}m</span>
                      )}
                    </div>
                  )}
                  {r.latitude && r.longitude && (
                    <a href={`https://www.google.com/maps?q=${r.latitude},${r.longitude}`} target="_blank" rel="noreferrer" style={{ color: 'var(--cyan)', fontWeight: 700 }}>
                      Abrir mapa
                    </a>
                  )}
                </div>
              </div>

              {r.status === 'pending' && (
                <div style={{ padding: '14px 20px', borderTop: '1px solid var(--border)', display: 'grid', gap: 10 }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1.4fr)', gap: 10 }}>
                    <div>
                      <label className="form-label">Medição confirmada (m³)</label>
                      <input className="form-input" inputMode="decimal" value={draftValues[r.id] || ''} onChange={event => setDraftValues(current => ({ ...current, [r.id]: event.target.value }))} placeholder="Ex: 13,440" />
                    </div>
                    <div>
                      <label className="form-label">Motivo do ajuste <span style={{ fontWeight: 400 }}>(se houver)</span></label>
                      <input className="form-input" value={draftReasons[r.id] || ''} onChange={event => setDraftReasons(current => ({ ...current, [r.id]: event.target.value }))} placeholder="Ex: dígito em transição" />
                    </div>
                  </div>
                  <ReadingConfirmationPreview reading={r} rawValue={draftValues[r.id] || ''} />
                  <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                    <button className="btn btn-danger btn-sm" onClick={() => reject(r.id)} disabled={actionLoading === r.id}>
                      <X size={14} /> Solicitar nova captura
                    </button>
                    {(r.vision_predicted_value ?? r.photo_extracted_value) !== null && (
                      <button className="btn btn-secondary btn-sm" onClick={() => approve(r, true)} disabled={actionLoading === r.id}>
                        <Sparkles size={14} /> Confirmar sugestão
                      </button>
                    )}
                    <button className="btn btn-primary btn-sm" onClick={() => approve(r)} disabled={actionLoading === r.id}>
                      {actionLoading === r.id ? <div className="spinner" style={{ width: 14, height: 14 }} /> : <Check size={14} />}
                      Confirmar valor e faturar
                    </button>
                  </div>
                </div>
              )}

              {r.status === 'rejected' && r.rejection_reason && (
                <div style={{ padding: '10px 20px', borderTop: '1px solid var(--border)', fontSize: 12, color: 'var(--danger)' }}>
                  Motivo: {r.rejection_reason}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

function ReadingPhoto({ url, label }: { url: string | null; label?: string }) {
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  if (!url || failed) {
    return (
      <div style={{ width: 120, height: 90, borderRadius: 8, background: 'var(--blue-50)', display: 'grid', placeItems: 'center', color: 'var(--text-muted)' }}>
        Sem foto
      </div>
    );
  }

  const resolvedUrl = url.startsWith('http') ? url : `${API_BASE}${url}`;
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label={`Abrir ${label || 'foto da leitura'}`}
        style={{ width: 120, padding: 0, border: 0, background: 'transparent', cursor: 'zoom-in', textAlign: 'left' }}
      >
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={resolvedUrl}
          alt={label || 'Foto da leitura'}
          onError={() => setFailed(true)}
          style={{ width: 120, height: 90, objectFit: 'cover', borderRadius: 8, border: '1px solid var(--border)', display: 'block' }}
        />
        {label && <span style={{ display: 'block', marginTop: 4, fontSize: 10, color: 'var(--text-muted)', textAlign: 'center' }}>{label}</span>}
      </button>
      {open && (
        <div
          role="dialog"
          aria-modal="true"
          onClick={() => setOpen(false)}
          style={{ position: 'fixed', inset: 0, zIndex: 1000, background: 'rgba(2, 8, 23, 0.88)', display: 'grid', placeItems: 'center', padding: 24, cursor: 'zoom-out' }}
        >
          <div style={{ maxWidth: '95vw', maxHeight: '92vh', display: 'grid', gap: 10, justifyItems: 'center' }} onClick={event => event.stopPropagation()}>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={resolvedUrl} alt={label || 'Foto da leitura ampliada'} style={{ maxWidth: '95vw', maxHeight: '82vh', objectFit: 'contain', borderRadius: 10 }} />
            <div style={{ color: '#fff', display: 'flex', gap: 12, alignItems: 'center' }}>
              <span>{label || 'Foto da leitura'}</span>
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => setOpen(false)}>Fechar</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

function ReadingConfirmationPreview({ reading, rawValue }: { reading: Reading; rawValue: string }) {
  const value = Number(rawValue.replace(',', '.'));
  if (!Number.isFinite(value)) return null;
  const suggestion = reading.vision_predicted_value ?? reading.photo_extracted_value;
  const adjusted = suggestion !== null && Math.abs(value - suggestion) > 0.0005;
  const consumption = value >= reading.previous_value ? value - reading.previous_value : null;

  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', padding: '8px 10px', borderRadius: 8, background: adjusted ? 'var(--warning-soft)' : 'var(--success-soft)', color: adjusted ? 'var(--warning)' : 'var(--success)', fontSize: 12, fontWeight: 700 }}>
      <span>{adjusted ? 'Valor ajustado' : 'Sugestão preservada'}</span>
      <span>•</span>
      <span>{consumption === null ? 'Virada/regressão será validada pelo servidor' : `Consumo previsto: ${consumption.toFixed(3)} m³`}</span>
    </div>
  );
}
