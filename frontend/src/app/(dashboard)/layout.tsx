'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { AuthProvider, useAuth } from '@/lib/auth';
import { api } from '@/lib/api';
import Sidebar from '@/components/Sidebar';

function ProtectedShell({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace('/login');
  }, [loading, user, router]);

  useEffect(() => {
    if (!loading && user) {
      [
        '/painel',
        '/clientes',
        '/hidrometros',
        '/leituras',
        '/faturas',
        '/tarifas',
        '/configuracoes',
      ].forEach(route => router.prefetch(route));

      const warmData = () => api.prefetch([
        '/dashboard',
        '/customers?per_page=1000',
        '/hydrometers',
        '/readings?status=pending&per_page=50',
        '/invoices?page=1&per_page=20',
        '/tariffs',
        '/system-settings',
        '/deductions',
        ...(user.role === 'admin' ? ['/auth/users'] : []),
      ]);

      const idleCallback = window.requestIdleCallback;
      if (idleCallback) {
        idleCallback(warmData, { timeout: 2000 });
      } else {
        setTimeout(warmData, 500);
      }
    }
  }, [loading, user, router]);

  if (loading) {
    return (
      <div className="loading-page">
        <div className="spinner" style={{ width: 32, height: 32 }} />
        <span>Carregando...</span>
      </div>
    );
  }

  if (!user) return null;

  return (
    <div className="app-layout">
      <Sidebar />
      <main className="app-main">{children}</main>
    </div>
  );
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthProvider>
      <ProtectedShell>{children}</ProtectedShell>
    </AuthProvider>
  );
}
