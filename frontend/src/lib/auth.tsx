'use client';

/* eslint-disable react-hooks/set-state-in-effect */

import { createContext, useContext, useEffect, useState, useCallback, ReactNode } from 'react';
import { api } from '@/lib/api';

interface User {
  id: string;
  name: string;
  email: string;
  role: string;
  is_active: boolean;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<User | null>;
  setCurrentUser: (user: User) => void;
  isAdmin: boolean;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const loadUser = useCallback(async (): Promise<User | null> => {
    const token = localStorage.getItem('token');
    if (!token) {
      setLoading(false);
      return null;
    }

    const cached = localStorage.getItem('user');
    if (cached) {
      try {
        setUser(JSON.parse(cached));
      } catch {
        // Ignore malformed cached user.
      }
    }

    try {
      const nextUser = await api.get<User>('/auth/me');
      setUser(nextUser);
      localStorage.setItem('user', JSON.stringify(nextUser));
      return nextUser;
    } catch (err: unknown) {
      if (err instanceof Error && err.message === 'NÃ£o autorizado') {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        setUser(null);
      }
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadUser();
  }, [loadUser]);

  const login = async (email: string, password: string) => {
    const res = await api.post<{ access_token: string; name: string; role: string; user_id: string }>(
      '/auth/login', { email, password }
    );
    localStorage.setItem('token', res.access_token);
    const userData: User = { id: res.user_id, name: res.name, email, role: res.role, is_active: true };
    localStorage.setItem('user', JSON.stringify(userData));
    setUser(userData);
  };

  const logout = () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    setUser(null);
    window.location.href = '/login';
  };

  const setCurrentUser = (nextUser: User) => {
    localStorage.setItem('user', JSON.stringify(nextUser));
    setUser(nextUser);
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        loading,
        login,
        logout,
        refreshUser: loadUser,
        setCurrentUser,
        isAdmin: user?.role === 'admin',
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth deve ser usado dentro de AuthProvider');
  return ctx;
}
