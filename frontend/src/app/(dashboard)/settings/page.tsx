'use client';

/* eslint-disable react-hooks/set-state-in-effect */

import { useEffect, useMemo, useState, FormEvent, useCallback } from 'react';
import Header from '@/components/Header';
import { api } from '@/lib/api';
import { useAuth } from '@/lib/auth';
import { BACKEND_FRAMEWORK, BUILD_REVISION, DEPLOY_TARGET, FRONTEND_FRAMEWORK, FRONTEND_VERSION } from '@/lib/app-info';
import { Database, Globe, Key, Server, Plus, Pencil, Trash2, Save, X, Loader2, ShieldCheck, Sparkles } from 'lucide-react';

interface Deduction {
  id: string;
  label: string;
  amount: number;
  is_active: boolean;
  sort_order: number;
}

interface HealthData {
  status: string;
  app: string;
  version: string;
  revision: string;
  whatsapp_enabled: boolean;
  inter_sandbox: boolean;
}

interface ManagedUser {
  id: string;
  name: string;
  email: string;
  role: string;
  is_active: boolean;
}

function fmt(v: number) {
  return new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(v);
}

export default function SettingsPage() {
  const { user, setCurrentUser } = useAuth();
  const [deductions, setDeductions] = useState<Deduction[]>([]);
  const [total, setTotal] = useState(0);
  const [health, setHealth] = useState<HealthData | null>(null);
  const [loading, setLoading] = useState(true);
  const [editId, setEditId] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({ label: '', amount: '' });
  const [saving, setSaving] = useState(false);
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileMessage, setProfileMessage] = useState<string | null>(null);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [users, setUsers] = useState<ManagedUser[]>([]);
  const [usersLoading, setUsersLoading] = useState(true);
  const [userSaving, setUserSaving] = useState(false);
  const [userMessage, setUserMessage] = useState<string | null>(null);
  const [userError, setUserError] = useState<string | null>(null);
  const [newUserForm, setNewUserForm] = useState({
    name: '',
    email: '',
    password: '',
    role: 'collaborator',
  });
  const [profileForm, setProfileForm] = useState<{
    name: string | null;
    email: string | null;
    current_password: string;
    new_password: string;
  }>({
    name: null,
    email: null,
    current_password: '',
    new_password: '',
  });
  const defaultProfileValues = useMemo(() => ({
    name: user?.name || '',
    email: user?.email || '',
  }), [user?.email, user?.name]);

  const load = useCallback(() => {
    setLoading(true);
    setUsersLoading(user?.role === 'admin');
    Promise.all([
      api.get<{ items: Deduction[]; total: number }>('/deductions'),
      api.get<HealthData>('/health'),
      user?.role === 'admin'
        ? api.get<{ items: ManagedUser[]; total: number }>('/auth/users')
        : Promise.resolve(null),
    ])
      .then(([deductionData, healthData, usersData]) => {
        setDeductions(deductionData.items);
        setTotal(deductionData.total);
        setHealth(healthData);
        if (usersData) {
          setUsers(usersData.items);
        }
      })
      .catch(console.error)
      .finally(() => {
        setLoading(false);
        setUsersLoading(false);
      });
  }, [user?.role]);

  useEffect(() => {
    load();
  }, [load]);

  const handleAdd = async (e: FormEvent) => {
    e.preventDefault();
    if (!form.label || !form.amount) return;
    setSaving(true);
    try {
      await api.post('/deductions', { label: form.label, amount: parseFloat(form.amount), sort_order: deductions.length });
      setForm({ label: '', amount: '' });
      setShowAdd(false);
      load();
    } catch (err) {
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  const handleUpdate = async (id: string) => {
    if (!form.label || !form.amount) return;
    setSaving(true);
    try {
      await api.patch(`/deductions/${id}`, { label: form.label, amount: parseFloat(form.amount) });
      setEditId(null);
      setForm({ label: '', amount: '' });
      load();
    } catch (err) {
      console.error(err);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Remover esta dedução?')) return;
    try {
      await api.delete(`/deductions/${id}`);
      load();
    } catch (err) {
      console.error(err);
    }
  };

  const handleProfileSave = async (e: FormEvent) => {
    e.preventDefault();
    setProfileSaving(true);
    setProfileError(null);
    setProfileMessage(null);
    const activeProfile = {
      name: (profileForm.name ?? defaultProfileValues.name).trim(),
      email: (profileForm.email ?? defaultProfileValues.email).trim(),
      current_password: profileForm.current_password,
      new_password: profileForm.new_password,
    };

    try {
      const payload: Record<string, string> = {
        name: activeProfile.name,
        email: activeProfile.email,
      };
      if (activeProfile.new_password) {
        payload.current_password = activeProfile.current_password;
        payload.new_password = activeProfile.new_password;
      }

      const updatedUser = await api.patch<{
        id: string;
        name: string;
        email: string;
        role: string;
        is_active: boolean;
      }>('/auth/me', payload);

      setCurrentUser(updatedUser);
      setProfileForm({
        name: updatedUser.name,
        email: updatedUser.email,
        current_password: '',
        new_password: '',
      });
      setProfileMessage('Perfil atualizado com sucesso.');
    } catch (err: unknown) {
      setProfileError(err instanceof Error ? err.message : 'Não foi possível atualizar seu perfil.');
    } finally {
      setProfileSaving(false);
    }
  };

  const handleCreateUser = async (e: FormEvent) => {
    e.preventDefault();
    setUserSaving(true);
    setUserError(null);
    setUserMessage(null);

    try {
      await api.post('/auth/register', {
        name: newUserForm.name.trim(),
        email: newUserForm.email.trim(),
        password: newUserForm.password,
        role: newUserForm.role,
      });
      setNewUserForm({
        name: '',
        email: '',
        password: '',
        role: 'collaborator',
      });
      setUserMessage('Usuário criado com sucesso.');
      load();
    } catch (err: unknown) {
      setUserError(err instanceof Error ? err.message : 'Não foi possível criar o usuário.');
    } finally {
      setUserSaving(false);
    }
  };

  const handleToggleUser = async (targetUser: ManagedUser) => {
    setUserSaving(true);
    setUserError(null);
    setUserMessage(null);

    try {
      await api.patch(`/auth/users/${targetUser.id}`, {
        is_active: !targetUser.is_active,
      });
      setUserMessage(`Usuário ${targetUser.is_active ? 'desativado' : 'reativado'} com sucesso.`);
      load();
    } catch (err: unknown) {
      setUserError(err instanceof Error ? err.message : 'Não foi possível atualizar o usuário.');
    } finally {
      setUserSaving(false);
    }
  };

  const systemVersion = useMemo(() => {
    const backendVersion = health?.version || '1.0.0';
    return backendVersion === FRONTEND_VERSION ? backendVersion : `${backendVersion} / web ${FRONTEND_VERSION}`;
  }, [health]);

  const revisionLabel = (health?.revision || BUILD_REVISION || '').slice(0, 7);

  const startEdit = (d: Deduction) => {
    setEditId(d.id);
    setForm({ label: d.label, amount: d.amount.toString() });
    setShowAdd(false);
  };

  return (
    <>
      <Header title="Configurações" subtitle="Sistema, perfil e automações financeiras" />

      <div style={{ display: 'grid', gridTemplateColumns: '1.1fr 0.9fr', gap: 16, alignItems: 'start' }}>
        <div className="card subtle-watermark">
          <div className="card-header">
            <span className="card-title">Meu Perfil</span>
            <span className="badge active"><ShieldCheck size={12} /> {user?.role === 'admin' ? 'Administrador' : 'Colaborador'}</span>
          </div>
          <form onSubmit={handleProfileSave} className="form-grid" style={{ gridTemplateColumns: '1fr 1fr' }}>
            <div className="form-group">
              <label className="form-label">Nome</label>
              <input className="form-input" value={profileForm.name ?? defaultProfileValues.name} onChange={e => setProfileForm(f => ({ ...f, name: e.target.value }))} required />
            </div>
            <div className="form-group">
              <label className="form-label">E-mail</label>
              <input className="form-input" type="email" value={profileForm.email ?? defaultProfileValues.email} onChange={e => setProfileForm(f => ({ ...f, email: e.target.value }))} required />
            </div>
            <div className="form-group">
              <label className="form-label">Senha Atual</label>
              <input className="form-input" type="password" value={profileForm.current_password} onChange={e => setProfileForm(f => ({ ...f, current_password: e.target.value }))} placeholder="Somente se quiser trocar" />
            </div>
            <div className="form-group">
              <label className="form-label">Nova Senha</label>
              <input className="form-input" type="password" value={profileForm.new_password} onChange={e => setProfileForm(f => ({ ...f, new_password: e.target.value }))} placeholder="Opcional" />
            </div>
            <div style={{ gridColumn: '1 / -1', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginTop: 6 }}>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                {profileError ? <span style={{ color: 'var(--danger)' }}>{profileError}</span> : profileMessage || 'Seu perfil pode ser ajustado sem depender do administrador.'}
              </div>
              <button className="btn btn-primary btn-sm" type="submit" disabled={profileSaving}>
                {profileSaving ? <Loader2 size={14} className="spinner" /> : <Save size={14} />} Salvar perfil
              </button>
            </div>
          </form>
        </div>

        <div style={{ display: 'grid', gap: 16 }}>
          <SettingCard icon={<Database size={18} />} title="Banco de Dados" desc="Neon PostgreSQL Serverless" status="Conectado" statusColor="var(--success)" />
          <SettingCard icon={<Key size={18} />} title="Banco Inter" desc={health?.inter_sandbox ? 'Cobrança V3 em Sandbox' : 'Cobrança V3 em Produção'} status="Configurado" statusColor="var(--success)" />
          <SettingCard
            icon={<Globe size={18} />}
            title="WhatsApp"
            desc="Evolution API conectada ao backend"
            status={health?.whatsapp_enabled ? 'Ativado' : 'Desativado'}
            statusColor={health?.whatsapp_enabled ? 'var(--success)' : 'var(--warning)'}
          />
          <SettingCard icon={<Server size={18} />} title="Kimi K2.6 Vision" desc="OCR de hidrômetros e validação de consumo" status="Configurado" statusColor="var(--success)" />
        </div>
      </div>

      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-header">
          <span className="card-title">Deduções Mensais</span>
          <button className="btn btn-primary btn-sm" onClick={() => { setShowAdd(true); setEditId(null); setForm({ label: '', amount: '' }); }}>
            <Plus size={14} /> Nova dedução
          </button>
        </div>

        {showAdd && (
          <form onSubmit={handleAdd} style={{ display: 'flex', gap: 10, marginBottom: 16, padding: 14, background: 'var(--blue-50)', borderRadius: 'var(--radius-md)' }}>
            <input className="form-input" placeholder="Nome (ex: Energia)" value={form.label} onChange={e => setForm(f => ({ ...f, label: e.target.value }))} style={{ flex: 2 }} required />
            <input className="form-input" placeholder="Valor" type="number" step="0.01" value={form.amount} onChange={e => setForm(f => ({ ...f, amount: e.target.value }))} style={{ flex: 1 }} required />
            <button className="btn btn-primary btn-sm" type="submit" disabled={saving}>
              {saving ? <Loader2 size={14} className="spinner" /> : <Save size={14} />} Salvar
            </button>
            <button className="btn btn-ghost btn-sm" type="button" onClick={() => setShowAdd(false)}><X size={14} /></button>
          </form>
        )}

        {loading ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {[...Array(3)].map((_, i) => <div key={i} className="skeleton" style={{ height: 40 }} />)}
          </div>
        ) : deductions.length === 0 ? (
          <div className="empty-state" style={{ padding: 32 }}>
            <p>Nenhuma dedução cadastrada. Clique em &quot;Nova dedução&quot; para começar.</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            {deductions.map(d => (
              <div key={d.id}>
                {editId === d.id ? (
                  <div style={{ display: 'flex', gap: 10, padding: 10, background: 'var(--blue-50)', borderRadius: 'var(--radius-md)' }}>
                    <input className="form-input" value={form.label} onChange={e => setForm(f => ({ ...f, label: e.target.value }))} style={{ flex: 2 }} />
                    <input className="form-input" type="number" step="0.01" value={form.amount} onChange={e => setForm(f => ({ ...f, amount: e.target.value }))} style={{ flex: 1 }} />
                    <button className="btn btn-primary btn-sm" onClick={() => handleUpdate(d.id)} disabled={saving}>
                      {saving ? <Loader2 size={14} className="spinner" /> : <Save size={14} />}
                    </button>
                    <button className="btn btn-ghost btn-sm" onClick={() => setEditId(null)}><X size={14} /></button>
                  </div>
                ) : (
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 4px', borderBottom: '1px solid var(--border)' }}>
                    <span style={{ fontSize: 14, color: 'var(--text-primary)' }}>{d.label}</span>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                      <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--danger)' }}>- {fmt(d.amount)}</span>
                      <button className="btn btn-ghost btn-icon btn-sm" onClick={() => startEdit(d)}><Pencil size={13} /></button>
                      <button className="btn btn-ghost btn-icon btn-sm" onClick={() => handleDelete(d.id)} style={{ color: 'var(--danger)' }}><Trash2 size={13} /></button>
                    </div>
                  </div>
                )}
              </div>
            ))}
            <div style={{ display: 'flex', justifyContent: 'space-between', padding: '14px 4px 4px', fontWeight: 700 }}>
              <span>Total mensal</span>
              <span style={{ color: 'var(--danger)' }}>- {fmt(total)}</span>
            </div>
          </div>
        )}
      </div>

      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-header"><span className="card-title">Informações do Sistema</span></div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13, color: 'var(--text-secondary)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Versão</span><span style={{ fontWeight: 600 }}>{systemVersion}</span></div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Backend</span><span style={{ fontWeight: 600 }}>{BACKEND_FRAMEWORK}</span></div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Frontend</span><span style={{ fontWeight: 600 }}>{FRONTEND_FRAMEWORK}</span></div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Deploy</span><span style={{ fontWeight: 600 }}>{DEPLOY_TARGET}</span></div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Revisão</span><span style={{ fontWeight: 600 }}>{revisionLabel || 'local'}</span></div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Status</span><span style={{ fontWeight: 600 }}>{health?.status || 'carregando'}</span></div>
        </div>
        <div className="easter-egg-note">
          <Sparkles size={12} />
          <span>kaceratw</span>
        </div>
      </div>

      {user?.role === 'admin' && (
        <div className="card" style={{ marginTop: 24 }}>
          <div className="card-header">
            <span className="card-title">Usuários do Sistema</span>
          </div>

          <form onSubmit={handleCreateUser} className="form-grid" style={{ gridTemplateColumns: '1.2fr 1.2fr 1fr 0.8fr auto', marginBottom: 18 }}>
            <input
              className="form-input"
              placeholder="Nome"
              value={newUserForm.name}
              onChange={e => setNewUserForm(current => ({ ...current, name: e.target.value }))}
              required
            />
            <input
              className="form-input"
              type="email"
              placeholder="E-mail"
              value={newUserForm.email}
              onChange={e => setNewUserForm(current => ({ ...current, email: e.target.value }))}
              required
            />
            <input
              className="form-input"
              type="password"
              placeholder="Senha inicial"
              value={newUserForm.password}
              onChange={e => setNewUserForm(current => ({ ...current, password: e.target.value }))}
              required
            />
            <select
              className="form-select"
              value={newUserForm.role}
              onChange={e => setNewUserForm(current => ({ ...current, role: e.target.value }))}
            >
              <option value="collaborator">Colaborador</option>
              <option value="admin">Administrador</option>
            </select>
            <button className="btn btn-primary btn-sm" type="submit" disabled={userSaving}>
              {userSaving ? <Loader2 size={14} className="spinner" /> : <Plus size={14} />} Criar
            </button>
          </form>

          {(userMessage || userError) && (
            <div style={{ marginBottom: 14, fontSize: 12, color: userError ? 'var(--danger)' : 'var(--success)' }}>
              {userError || userMessage}
            </div>
          )}

          {usersLoading ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {[...Array(3)].map((_, i) => <div key={i} className="skeleton" style={{ height: 40 }} />)}
            </div>
          ) : (
            <div className="table-wrapper" style={{ border: 'none' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Nome</th>
                    <th>E-mail</th>
                    <th>Perfil</th>
                    <th>Status</th>
                    <th>Ação</th>
                  </tr>
                </thead>
                <tbody>
                  {!users.length ? (
                    <tr><td colSpan={5}><div className="empty-state" style={{ padding: 20 }}><p>Nenhum usuário cadastrado.</p></div></td></tr>
                  ) : users.map(managedUser => (
                    <tr key={managedUser.id}>
                      <td className="cell-primary">{managedUser.name}</td>
                      <td>{managedUser.email}</td>
                      <td>{managedUser.role === 'admin' ? 'Administrador' : 'Colaborador'}</td>
                      <td><span className={`badge ${managedUser.is_active ? 'active' : 'suspended'}`}>{managedUser.is_active ? 'Ativo' : 'Desativado'}</span></td>
                      <td>
                        <button className="btn btn-secondary btn-sm" type="button" disabled={userSaving || managedUser.id === user.id} onClick={() => handleToggleUser(managedUser)}>
                          {managedUser.is_active ? 'Desativar' : 'Reativar'}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  );
}

function SettingCard({ icon, title, desc, status, statusColor }: {
  icon: React.ReactNode; title: string; desc: string; status: string; statusColor: string;
}) {
  return (
    <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
      <div className="kpi-icon blue" style={{ width: 44, height: 44, flexShrink: 0 }}>{icon}</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>{title}</div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{desc}</div>
      </div>
      <div style={{ fontSize: 12, fontWeight: 600, color: statusColor }}>{status}</div>
    </div>
  );
}
