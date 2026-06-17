'use client';

/* eslint-disable react-hooks/set-state-in-effect */

import { useEffect, useState, useCallback } from 'react';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { useAppFeedback } from '@/components/AppFeedbackProvider';
import { AlertTriangle, ClipboardCheck, Check, X, Camera, MapPin } from 'lucide-react';

const API_BASE = (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api').replace(/\/api$/, '');

interface Reading {
  id: string;
  current_value: number;
  previous_value: number;
  consumption: number;
  photo_url: string;
  photo_extracted_code: string;
  photo_extracted_value: number;
  ocr_confidence: number;
  latitude: number;
  longitude: number;
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

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<ListRes>(`/readings?status=${filter}&per_page=50`, { skipCache: true });
      setData(res);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  }, [filter]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        void load();
      }
    }, 5000);
    const handleFocus = () => void load();
    window.addEventListener('focus', handleFocus);
    return () => {
      window.clearInterval(interval);
      window.removeEventListener('focus', handleFocus);
    };
  }, [load]);

  const approve = async (id: string) => {
    setActionLoading(id);
    try {
      await api.post(`/readings/${id}/approve`);
      notify('Leitura aprovada', 'A leitura foi enviada para o próximo fluxo de faturamento.', 'success');
      await load();
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
      notify('Leitura rejeitada', 'O motivo foi salvo para revisão posterior.', 'warning');
      await load();
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
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(380px, 1fr))', gap: 16 }}>
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
                  <div><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Atual</div><div style={{ fontWeight: 600 }}>{r.current_value.toFixed(2)}</div></div>
                  <div><div style={{ fontSize: 11, color: 'var(--text-muted)' }}>Consumo</div><div style={{ fontWeight: 700, color: 'var(--cyan)' }}>{r.consumption.toFixed(2)} m³</div></div>
                </div>

                {r.ocr_confidence !== null && (
                  <div style={{ marginTop: 10, fontSize: 12, color: 'var(--text-muted)' }}>
                    OCR: {(r.ocr_confidence * 100).toFixed(0)}% confiança
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

              <div style={{ padding: '0 20px 14px', display: 'grid', gridTemplateColumns: '120px 1fr', gap: 12, alignItems: 'center' }}>
                <ReadingPhoto url={r.photo_url} />
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
                <div style={{ padding: '12px 20px', borderTop: '1px solid var(--border)', display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                  <button className="btn btn-danger btn-sm" onClick={() => reject(r.id)} disabled={actionLoading === r.id}>
                    <X size={14} /> Rejeitar
                  </button>
                  <button className="btn btn-primary btn-sm" onClick={() => approve(r.id)} disabled={actionLoading === r.id}>
                    {actionLoading === r.id ? <div className="spinner" style={{ width: 14, height: 14 }} /> : <Check size={14} />}
                    {alertTone(r.validation_flags || []) === 'danger' ? 'Aprovar mesmo assim' : 'Aprovar'}
                  </button>
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

function ReadingPhoto({ url }: { url: string | null }) {
  const [failed, setFailed] = useState(false);
  if (!url || failed) {
    return (
      <div style={{ width: 120, height: 90, borderRadius: 8, background: 'var(--blue-50)', display: 'grid', placeItems: 'center', color: 'var(--text-muted)' }}>
        Sem foto
      </div>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img
      src={url.startsWith('http') ? url : `${API_BASE}${url}`}
      alt="Foto da leitura"
      onError={() => setFailed(true)}
      style={{ width: 120, height: 90, objectFit: 'cover', borderRadius: 8, border: '1px solid var(--border)' }}
    />
  );
}
