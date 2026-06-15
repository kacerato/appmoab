'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { AuthProvider, useAuth } from '@/lib/auth';
import Sidebar from '@/components/Sidebar';
import { api } from '@/lib/api';

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

      const warmup = () => api.prefetch([
        '/dashboard?scope=month',
        '/customers?page=1&per_page=20',
        '/invoices?page=1&per_page=20',
        '/readings?status=pending&per_page=50',
        '/tariffs',
        '/system-settings',
      ]);

      if ('requestIdleCallback' in window) {
        const id = window.requestIdleCallback(warmup, { timeout: 1800 });
        return () => window.cancelIdleCallback(id);
      }

      const id = globalThis.setTimeout(warmup, 700);
      return () => globalThis.clearTimeout(id);
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
