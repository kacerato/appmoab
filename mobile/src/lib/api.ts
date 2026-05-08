import * as SecureStore from 'expo-secure-store';

const appConfig = require('../../app.json');
const apiUrlFromConfig =
  process.env.EXPO_PUBLIC_API_URL ||
  appConfig?.expo?.extra?.apiUrl ||
  'http://localhost:8000/api';

export const API_URL = apiUrlFromConfig.replace(/\/+$/, '');

let cachedToken: string | null = null;

export async function getToken(): Promise<string | null> {
  if (cachedToken) return cachedToken;
  cachedToken = await SecureStore.getItemAsync('token');
  return cachedToken;
}

export async function setToken(token: string): Promise<void> {
  cachedToken = token;
  await SecureStore.setItemAsync('token', token);
}

export async function clearToken(): Promise<void> {
  cachedToken = null;
  await SecureStore.deleteItemAsync('token');
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = await getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) || {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (res.status === 401) {
    await clearToken();
    throw new Error('SESSION_EXPIRED');
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Erro ${res.status}`);
  }

  if (res.status === 204) return {} as T;
  return res.json();
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
};
