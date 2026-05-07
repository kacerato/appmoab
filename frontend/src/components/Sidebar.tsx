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
  { href: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/customers', label: 'Clientes', icon: Users },
  { href: '/hydrometers', label: 'Hidrômetros', icon: Droplets },
  { section: 'Operações' },
  { href: '/readings', label: 'Leituras', icon: ClipboardCheck },
  { href: '/invoices', label: 'Faturas', icon: FileText },
  { section: 'Configurações' },
  { href: '/tariffs', label: 'Tarifas', icon: DollarSign },
  { href: '/notifications', label: 'Notificações', icon: Bell },
  { href: '/settings', label: 'Configurações', icon: Settings },
];

export default function Sidebar() {
  const { user, logout } = useAuth();
  const pathname = usePathname();

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-brand-icon">A</div>
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
        <button className="sidebar-link" onClick={logout} style={{ color: 'var(--danger)' }}>
          <LogOut /> Sair
        </button>
      </div>
    </aside>
  );
}
