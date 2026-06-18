'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { AuthProvider, useAuth } from '@/lib/auth';
import Sidebar from '@/components/Sidebar';
import { api } from '@/lib/api';
import { PRIMARY_DATA_PATHS, SECONDARY_DATA_PATHS } from '@/lib/route-prefetch';

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

      // As telas mais usadas aquecem imediatamente. O restante fica para ociosidade.
      api.prefetch(PRIMARY_DATA_PATHS);
      const warmup = () => api.prefetch(SECONDARY_DATA_PATHS);

      if ('requestIdleCallback' in window) {
        const id = window.requestIdleCallback(warmup, { timeout: 700 });
        return () => window.cancelIdleCallback(id);
      }

      const id = globalThis.setTimeout(warmup, 250);
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
