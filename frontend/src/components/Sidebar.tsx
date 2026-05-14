'use client';

import { useAuth } from '@/lib/auth';
import { usePathname } from 'next/navigation';
import Link from 'next/link';
import {
  LayoutDashboard, Users, Droplets, ClipboardCheck, FileText,
  DollarSign, Settings, Bell, LogOut, ChevronRight
} from 'lucide-react';
import { LucideIcon } from 'lucide-react';

type NavSection = { section: string };
type NavLink = { href: string; label: string; icon: LucideIcon };
type NavItem = NavSection | NavLink;

const NAV_ITEMS: NavItem[] = [
  { section: 'Principal' },
  { href: '/painel', label: 'Painel', icon: LayoutDashboard },
  { href: '/clientes', label: 'Clientes', icon: Users },
  { href: '/hidrometros', label: 'Hidrômetros', icon: Droplets },
  { section: 'Operações' },
  { href: '/leituras', label: 'Leituras', icon: ClipboardCheck },
  { href: '/faturas', label: 'Faturas', icon: FileText },
  { section: 'Configurações' },
  { href: '/tarifas', label: 'Tarifas', icon: DollarSign },
  { href: '/notificacoes', label: 'Notificações', icon: Bell },
  { href: '/configuracoes', label: 'Configurações', icon: Settings },
];

export default function Sidebar() {
  const { user, logout } = useAuth();
  const pathname = usePathname();

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-brand-icon" aria-hidden="true">
          <svg viewBox="0 0 64 64" role="img">
            <defs>
              <linearGradient id="sidebar-bg" x1="0" x2="1" y1="0" y2="1">
                <stop offset="0%" stopColor="#08213b" />
                <stop offset="100%" stopColor="#0e4f7f" />
              </linearGradient>
              <linearGradient id="sidebar-drop" x1="0" x2="1" y1="0" y2="1">
                <stop offset="0%" stopColor="#76d4ff" />
                <stop offset="100%" stopColor="#29a3ff" />
              </linearGradient>
            </defs>
            <rect width="64" height="64" rx="18" fill="url(#sidebar-bg)" />
            <path d="M32 10c-7 9-14 16-14 25 0 8 6 14 14 14s14-6 14-14c0-9-7-16-14-25Z" fill="url(#sidebar-drop)" />
            <circle cx="32" cy="36" r="7" fill="#08213b" opacity=".22" />
          </svg>
        </div>
        <div>
          <h1>AquaMoab</h1>
          <span>Gestão de Água</span>
        </div>
      </div>

      <nav className="sidebar-nav">
        {NAV_ITEMS.map((item, i) => {
          if ('section' in item) {
            return <div key={i} className="sidebar-section">{item.section}</div>;
          }
          const Icon = item.icon;
          const isActive = pathname === item.href || pathname?.startsWith(item.href + '/');
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`sidebar-link ${isActive ? 'active' : ''}`}
            >
              <Icon />
              <span>{item.label}</span>
              {isActive && <ChevronRight style={{ marginLeft: 'auto', width: 14, height: 14 }} />}
            </Link>
          );
        })}
      </nav>

      <div style={{ padding: '16px 12px', borderTop: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 14px', marginBottom: 8 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 'var(--radius-md)',
            background: 'var(--accent-soft)', color: 'var(--accent)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontWeight: 700, fontSize: 13
          }}>
            {user?.name?.charAt(0).toUpperCase()}
          </div>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600 }}>{user?.name}</div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              {user?.role === 'admin' ? 'Administrador' : 'Colaborador'}
            </div>
          </div>
        </div>
        <div className="sidebar-whisper" aria-hidden="true">kaceratw</div>
        <button className="sidebar-link" onClick={logout} style={{ color: 'var(--danger)' }}>
          <LogOut /> Sair
        </button>
      </div>
    </aside>
  );
}
