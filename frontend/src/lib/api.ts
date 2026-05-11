const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
const getCache = new Map<string, { expiresAt: number; value: unknown }>();

function clearGetCache() {
  getCache.clear();
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const method = options.method || 'GET';
  const cacheKey = `${API_URL}${path}`;
  if (method === 'GET') {
    const cached = getCache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) return cached.value as T;
  }

  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((options.headers as Record<string, string>) || {}),
  };
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });

  if (res.status === 401) {
    if (typeof window !== 'undefined') {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    throw new Error('Não autorizado');
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `Erro ${res.status}`);
  }

  if (res.status === 204) {
    if (method !== 'GET') clearGetCache();
    return {} as T;
  }

  const data = await res.json();
  if (method === 'GET') {
    getCache.set(cacheKey, { value: data, expiresAt: Date.now() + 45000 });
  } else {
    clearGetCache();
  }
  return data;
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};
