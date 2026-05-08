'use client';

import { useState, FormEvent, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/lib/auth';
import { Droplets, Mail, Lock, Loader2, ArrowRight } from 'lucide-react';

export default function LoginPage() {
  const { login, user, loading: authLoading } = useAuth();
  const router = useRouter();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!authLoading && user) {
      router.replace('/painel');
    }
  }, [authLoading, user, router]);

  const handleSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      router.push('/painel');
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Credenciais inválidas');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login-page">
      {/* Left side — visual with water effects */}
      <div className="login-visual">
        <div className="water-drop" />
        <div className="water-drop" />
        <div className="water-drop" />
        <div className="water-drop" />
        <div className="water-drop" />
        <div className="water-ripple" />
        <div className="water-ripple" />

        <Droplets size={64} color="rgba(255,255,255,0.9)" style={{ zIndex: 1, marginBottom: 16 }} />
        <h2>AquaMoab</h2>
        <p>
          Sistema inteligente de gestão e distribuição de água.
          Controle de leituras, faturamento e cobranças em um só lugar.
        </p>
      </div>

      {/* Right side — login form */}
      <div className="login-form-side">
        <div className="login-card">
          <div className="login-logo">
            <div className="login-logo-icon">
              <Droplets size={28} />
            </div>
            <h1>Bem-vindo</h1>
            <p>Faça login para continuar</p>
          </div>

          {error && <div className="login-error">{error}</div>}

          <form className="login-form" onSubmit={handleSubmit}>
            <div className="form-group">
              <label className="form-label">Email</label>
              <div style={{ position: 'relative' }}>
                <Mail size={16} style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                <input
                  className="form-input"
                  type="email"
                  placeholder="seu@email.com"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                  style={{ paddingLeft: 42 }}
                />
              </div>
            </div>

            <div className="form-group">
              <label className="form-label">Senha</label>
              <div style={{ position: 'relative' }}>
                <Lock size={16} style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }} />
                <input
                  className="form-input"
                  type="password"
                  placeholder="••••••••"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  required
                  autoComplete="current-password"
                  style={{ paddingLeft: 42 }}
                />
              </div>
            </div>

            <button className="btn btn-primary" type="submit" disabled={loading}>
              {loading ? (
                <><Loader2 size={16} className="spinner" /> Entrando...</>
              ) : (
                <>Entrar <ArrowRight size={16} /></>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
