import * as SecureStore from 'expo-secure-store';

const appConfig = require('../../app.json');
const apiUrlFromConfig =
  process.env.EXPO_PUBLIC_API_URL ||
  appConfig?.expo?.extra?.apiUrl ||
  'http://localhost:8000/api';

export const API_URL = apiUrlFromConfig.replace(/\/+$/, '');
const REQUEST_TIMEOUT_MS = 15000;
const GET_RETRY_DELAY_MS = 1200;

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

function extractErrorMessage(payload: unknown): string | null {
  if (!payload) return null;

  if (typeof payload === 'string') {
    return payload;
  }

  if (Array.isArray(payload)) {
    const parts = payload
      .map(item => extractErrorMessage(item))
      .filter((item): item is string => Boolean(item));
    return parts.length ? parts.join(' | ') : null;
  }

  if (typeof payload === 'object') {
    const record = payload as Record<string, unknown>;

    if (typeof record.msg === 'string') return record.msg;
    if (typeof record.message === 'string') return record.message;
    if (typeof record.detail === 'string') return record.detail;

    if (Array.isArray(record.loc) && typeof record.msg === 'string') {
      return `${record.loc.join(' > ')}: ${record.msg}`;
    }

    for (const value of Object.values(record)) {
      const nested = extractErrorMessage(value);
      if (nested) return nested;
    }
  }

  return null;
}

async function request<T>(path: string, options: RequestInit = {}, timeoutMs = REQUEST_TIMEOUT_MS): Promise<T> {
  const token = await getToken();
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) || {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  let res: Response;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  try {
    res = await fetch(`${API_URL}${path}`, { ...options, headers, signal: controller.signal });
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') {
      throw new Error('O servidor demorou para responder. Verifique sua conexao e tente novamente.');
    }
    throw new Error('Nao foi possivel conectar ao servidor. Verifique a URL da API e sua internet.');
  } finally {
    clearTimeout(timeoutId);
  }

  if (!res.ok) {
    const err = await res.json().catch(() => null);
    const message = extractErrorMessage(err) || `Erro ${res.status}`;
    if (res.status === 401 || (res.status === 403 && /not authenticated|token/i.test(message))) {
      await clearToken();
      throw new Error('SESSION_EXPIRED');
    }
    throw new Error(message);
  }

  if (res.status === 204) return {} as T;
  return res.json();
}

export const api = {
  get: async <T>(path: string) => {
    try {
      return await request<T>(path);
    } catch (error) {
      const message = error instanceof Error ? error.message : '';
      const isTransient =
        /demorou para responder|nao foi possivel conectar|Erro 5\d\d|Erro 429/i.test(message);

      // A mobile app commonly wakes before its hosted API or radio is ready.
      // Retrying an idempotent read once avoids exposing that short recovery
      // window as an operational error to the field operator.
      if (!isTransient) throw error;
      await new Promise(resolve => setTimeout(resolve, GET_RETRY_DELAY_MS));
      return request<T>(path);
    }
  },
  post: <T>(path: string, body?: unknown, timeoutMs?: number) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }, timeoutMs),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
};
