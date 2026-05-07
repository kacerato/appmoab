'use client';

import { useEffect, useState, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { Plus, Search, UserCheck, UserX, Droplets, ChevronLeft, ChevronRight } from 'lucide-react';

interface Customer {
  id: string; name: string; cpf_cnpj: string; phone: string; email: string;
  address: string; city: string; state: string; due_day: number;
  has_hydrometer: boolean; status: string; created_at: string;
}

interface ListRes { items: Customer[]; total: number; page: number; per_page: number; }

export default function CustomersPage() {
  const router = useRouter();
  const [data, setData] = useState<ListRes | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [page, setPage] = useState(1);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      let url = `/customers?page=${page}&per_page=20`;
      if (search) url += `&search=${encodeURIComponent(search)}`;
      if (statusFilter) url += `&status=${statusFilter}`;
      const res = await api.get<ListRes>(url);
      setData(res);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [page, search, statusFilter]);

  useEffect(() => { load(); }, [load]);

  const totalPages = data ? Math.ceil(data.total / data.per_page) : 0;

  return (
    <>
      <Header title="Clientes" subtitle={`${data?.total || 0} cadastrados`} />

      <div className="toolbar">
        <div className="search-box">
          <Search />
          <input
            placeholder="Buscar por nome, CPF ou telefone..."
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }}
          />
        </div>
        <select
          className="form-select"
          style={{ width: 160 }}
          value={statusFilter}
          onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
        >
          <option value="">Todos</option>
          <option value="active">Ativos</option>
          <option value="suspended">Suspensos</option>
          <option value="disconnected">Desligados</option>
        </select>
        <button className="btn btn-primary" onClick={() => router.push('/customers/new')}>
          <Plus size={16} /> Novo Cliente
        </button>
      </div>

      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th>Nome</th>
              <th>CPF/CNPJ</th>
              <th>Telefone</th>
              <th>Cidade</th>
              <th>Tipo</th>
              <th>Vencimento</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={7}><div className="loading-page" style={{ height: 200 }}><div className="spinner" /></div></td></tr>
            ) : !data?.items.length ? (
              <tr><td colSpan={7}><div className="empty-state"><p>Nenhum cliente encontrado</p></div></td></tr>
            ) : data.items.map(c => (
              <tr key={c.id} onClick={() => router.push(`/customers/${c.id}`)} style={{ cursor: 'pointer' }}>
                <td className="cell-primary">{c.name}</td>
                <td>{formatCpfCnpj(c.cpf_cnpj)}</td>
                <td>{c.phone || '—'}</td>
                <td>{c.city}/{c.state}</td>
                <td>
                  {c.has_hydrometer
                    ? <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--cyan)' }}><Droplets size={13} /> Medido</span>
                    : <span style={{ display: 'flex', alignItems: 'center', gap: 4, color: 'var(--text-muted)' }}><UserCheck size={13} /> Fixo</span>
                  }
                </td>
                <td>Dia {c.due_day}</td>
                <td><span className={`badge ${c.status}`}>{statusLabel(c.status)}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div className="pagination">
          <span>Página {page} de {totalPages} ({data?.total} resultados)</span>
          <div className="pagination-buttons">
            <button className="btn btn-secondary btn-sm" disabled={page <= 1} onClick={() => setPage(p => p - 1)}><ChevronLeft size={14} /></button>
            <button className="btn btn-secondary btn-sm" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}><ChevronRight size={14} /></button>
          </div>
        </div>
      )}
    </>
  );
}

function formatCpfCnpj(v: string) {
  if (v.length === 11) return v.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, '$1.$2.$3-$4');
  if (v.length === 14) return v.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, '$1.$2.$3/$4-$5');
  return v;
}

function statusLabel(s: string) {
  const m: Record<string, string> = { active: 'Ativo', suspended: 'Suspenso', disconnected: 'Desligado' };
  return m[s] || s;
}
