const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';
const getCache = new Map<string, { expiresAt: number; value: unknown }>();
const inFlight = new Map<string, Promise<unknown>>();
const GET_CACHE_TTL_MS = 5 * 60 * 1000;

type ApiRequestOptions = RequestInit & { skipCache?: boolean };

function clearGetCache() {
  getCache.clear();
  inFlight.clear();
}

async function request<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const { skipCache, ...fetchOptions } = options;
  const method = options.method || 'GET';
  const token = typeof window !== 'undefined' ? localStorage.getItem('token') : null;
  const cacheKey = `${token || 'anon'}:${API_URL}${path}`;
  if (method === 'GET' && !skipCache) {
    const cached = getCache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) return cached.value as T;
    const pending = inFlight.get(cacheKey);
    if (pending) return pending as Promise<T>;
  }

  const headers: Record<string, string> = { ...((fetchOptions.headers as Record<string, string>) || {}) };
  if (method !== 'GET' && options.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json';
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const fetchPromise = fetch(`${API_URL}${path}`, { ...fetchOptions, headers })
    .then(async (res) => {
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
        if (!skipCache) {
          getCache.set(cacheKey, { value: data, expiresAt: Date.now() + GET_CACHE_TTL_MS });
        }
      } else {
        clearGetCache();
      }
      return data as T;
    })
    .finally(() => {
      if (method === 'GET' && !skipCache) inFlight.delete(cacheKey);
    });

  if (method === 'GET' && !skipCache) {
    inFlight.set(cacheKey, fetchPromise);
  }
  return fetchPromise;
}

export const api = {
  get: <T>(path: string, options?: ApiRequestOptions) => request<T>(path, options),
  prefetch: (paths: string[]) => {
    paths.forEach(path => {
      void request<unknown>(path).catch(() => undefined);
    });
  },
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
  delete: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
};
