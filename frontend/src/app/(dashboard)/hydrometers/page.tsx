'use client';

import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { Droplets, Plus } from 'lucide-react';

interface Hydrometer {
  id: string; code: string; customer_id: string; brand: string; model: string;
  location_description: string; last_reading_value: number; last_reading_date: string;
  is_active: boolean; installed_at: string;
}

export default function HydrometersPage() {
  const [items, setItems] = useState<Hydrometer[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<{ items: Hydrometer[] }>('/hydrometers')
      .then(r => setItems(r.items))
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  return (
    <>
      <Header title="Hidrômetros" subtitle={`${items.length} cadastrados`} />

      <div className="table-wrapper">
        <table className="data-table">
          <thead><tr><th>Código</th><th>Marca/Modelo</th><th>Última Leitura</th><th>Data</th><th>Status</th></tr></thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5}><div className="loading-page" style={{ height: 200 }}><div className="spinner" /></div></td></tr>
            ) : !items.length ? (
              <tr><td colSpan={5}><div className="empty-state"><Droplets /><p>Nenhum hidrômetro cadastrado</p></div></td></tr>
            ) : items.map(h => (
              <tr key={h.id}>
                <td className="cell-primary">{h.code}</td>
                <td>{[h.brand, h.model].filter(Boolean).join(' ') || '—'}</td>
                <td style={{ fontWeight: 600 }}>{h.last_reading_value.toFixed(2)} m³</td>
                <td>{h.last_reading_date ? new Date(h.last_reading_date).toLocaleDateString('pt-BR') : '—'}</td>
                <td><span className={`badge ${h.is_active ? 'active' : 'suspended'}`}>{h.is_active ? 'Ativo' : 'Inativo'}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
