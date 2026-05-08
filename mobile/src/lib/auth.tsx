import React, { createContext, useContext, useEffect, useState, useCallback, ReactNode } from 'react';
import { api, getToken, setToken, clearToken } from './api';
import * as SecureStore from 'expo-secure-store';

interface User {
  id: string;
  name: string;
  email: string;
  role: string;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const loadUser = useCallback(async () => {
    const token = await getToken();
    if (!token) { setLoading(false); return; }

    const cachedUser = await SecureStore.getItemAsync('user');
    if (cachedUser) {
      try { setUser(JSON.parse(cachedUser)); } catch { /* ignore */ }
    }

    try {
      const u = await api.get<User>('/auth/me');
      setUser(u);
      await SecureStore.setItemAsync('user', JSON.stringify(u));
    } catch (err: any) {
      if (err.message === 'SESSION_EXPIRED') {
        await clearToken();
        await SecureStore.deleteItemAsync('user');
        setUser(null);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadUser(); }, [loadUser]);

  const login = async (email: string, password: string) => {
    const res = await api.post<{ access_token: string; name: string; role: string; user_id: string }>(
      '/auth/login', { email, password }
    );
    await setToken(res.access_token);
    const userData: User = { id: res.user_id, name: res.name, email, role: res.role };
    await SecureStore.setItemAsync('user', JSON.stringify(userData));
    setUser(userData);
  };

  const logout = async () => {
    await clearToken();
    await SecureStore.deleteItemAsync('user');
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth deve ser usado dentro de AuthProvider');
  return ctx;
}
