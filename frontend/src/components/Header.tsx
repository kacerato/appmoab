'use client';

import { useAuth } from '@/lib/auth';
import { Bell } from 'lucide-react';

interface Props {
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
}

export default function Header({ title, subtitle, actions }: Props) {
  const { user } = useAuth();

  return (
    <header className="app-header">
      <div>
        <div className="header-title">{title}</div>
        {subtitle && <div className="header-subtitle">{subtitle}</div>}
      </div>
      <div className="header-actions">
        {actions}
        <button className="btn btn-ghost btn-icon" title="Notificações">
          <Bell size={18} />
        </button>
      </div>
    </header>
  );
}
