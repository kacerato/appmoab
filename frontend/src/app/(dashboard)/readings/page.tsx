'use client';

import { useEffect, useState, useCallback } from 'react';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { ClipboardCheck, Check, X, Eye, MapPin, Clock, Camera } from 'lucide-react';

interface Reading {
  id: string; current_value: number; previous_value: number; consumption: number;
  photo_url: string; photo_extracted_code: string; photo_extracted_value: number;
  ocr_confidence: number; latitude: number; longitude: number;
  captured_at: string; status: string; rejection_reason: string;
  collaborator_name: string; hydrometer_code: string; customer_name: string; customer_id: string;
}

interface ListRes { items: Reading[]; total: number; page: number; per_page: number; }

export default function ReadingsPage() {
  const [data, setData] = useState<ListRes | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('pending');
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get<ListRes>(`/readings?status=${filter}&per_page=50`);
      setData(res);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  const approve = async (id: string) => {
    setActionLoading(id);
    try {
      await api.post(`/readings/${id}/approve`);
      load();
    } catch (e) { alert(e instanceof Error ? e.message : 'Erro'); }
    finally { setActionLoading(null); }
  };

  const reject = async (id: string) => {
    const reason = prompt('Motivo da rejeição:');
    if (!reason) return;
    setActionLoading(id);
    try {
      await api.post(`/readings/${id}/reject`, { reason });
      load();
    } catch (e) { alert(e instanceof Error ? e.message : 'Erro'); }
    finally { setActionLoading(null); }
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
            <div key={r.id} className="card" style={{ padding: 0, overflow: 'hidden' }}>
              <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                  <div>
                    <div style={{ fontWeight: 700, fontSize: 15 }}>{r.customer_name || 'Cliente'}</div>
                    <div style={{ fontSize: 12, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
                      <Camera size={11} /> {r.hydrometer_code || 'N/A'}
                    </div>
                  </div>
                  <span className={`badge ${r.status}`}>{r.status === 'pending' ? 'Pendente' : r.status === 'approved' ? 'Aprovada' : 'Rejeitada'}</span>
                </div>

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
              </div>

              <div style={{ padding: '10px 20px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 12, color: 'var(--text-muted)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <Clock size={12} /> {new Date(r.captured_at).toLocaleString('pt-BR')}
                </div>
                <div>{r.collaborator_name}</div>
              </div>

              {r.status === 'pending' && (
                <div style={{ padding: '12px 20px', borderTop: '1px solid var(--border)', display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                  <button className="btn btn-danger btn-sm" onClick={() => reject(r.id)} disabled={actionLoading === r.id}>
                    <X size={14} /> Rejeitar
                  </button>
                  <button className="btn btn-primary btn-sm" onClick={() => approve(r.id)} disabled={actionLoading === r.id}>
                    {actionLoading === r.id ? <div className="spinner" style={{ width: 14, height: 14 }} /> : <Check size={14} />}
                    Aprovar
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
