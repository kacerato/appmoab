import * as SecureStore from 'expo-secure-store';

export const ROUTE_CACHE_KEY = 'route_screen_cache_v1';

export interface CachedHydrometer {
  id: string;
  code: string;
  qr_code_token?: string | null;
  last_reading_value?: number | null;
  red_digits?: number | null;
  black_digits?: number | null;
  brand?: string | null;
  model?: string | null;
  location_description?: string | null;
  last_reading_date?: string | null;
}

export interface CachedCustomer {
  id: string;
  name: string;
  hydrometers: CachedHydrometer[];
}

interface RouteCachePayload {
  customers?: CachedCustomer[];
}

export interface CachedHydrometerMatch {
  customer: CachedCustomer;
  hydrometer: CachedHydrometer;
}

export function normalizeScannedQrValue(value: string | null | undefined): string {
  const trimmed = (value || '').trim();
  if (!trimmed) return '';

  try {
    const parsed = new URL(trimmed);
    const token =
      parsed.searchParams.get('qr_code_token') ||
      parsed.searchParams.get('token') ||
      parsed.searchParams.get('code');

    if (token?.trim()) return token.trim();

    const lastSegment = parsed.pathname.split('/').filter(Boolean).pop();
    return lastSegment?.trim() || trimmed;
  } catch {
    return trimmed;
  }
}

function normalizeNumericCode(value: string | null | undefined): string {
  const raw = (value || '').trim();
  if (!raw || /[A-Za-z]/.test(raw)) return '';
  return raw.replace(/\D/g, '');
}

export function matchesHydrometerQr(scannedValue: string, hydrometer: Pick<CachedHydrometer, 'code' | 'qr_code_token'>): boolean {
  const scanned = normalizeScannedQrValue(scannedValue);
  if (!scanned) return false;

  const token = hydrometer.qr_code_token?.trim();
  if (token && scanned === token) return true;

  const code = hydrometer.code?.trim();
  if (code && scanned === code) return true;

  const scannedNumeric = normalizeNumericCode(scanned);
  const codeNumeric = normalizeNumericCode(code);
  return Boolean(scannedNumeric && codeNumeric && scannedNumeric === codeNumeric);
}

export async function findCachedHydrometerByQr(scannedValue: string): Promise<CachedHydrometerMatch | null> {
  const cached = await SecureStore.getItemAsync(ROUTE_CACHE_KEY).catch(() => null);
  if (!cached) return null;

  let parsed: RouteCachePayload;
  try {
    parsed = JSON.parse(cached) as RouteCachePayload;
  } catch {
    return null;
  }

  for (const customer of parsed.customers || []) {
    for (const hydrometer of customer.hydrometers || []) {
      if (matchesHydrometerQr(scannedValue, hydrometer)) {
        return { customer, hydrometer };
      }
    }
  }

  return null;
}
