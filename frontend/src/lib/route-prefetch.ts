import { api } from '@/lib/api';

const ROUTE_DATA: Record<string, string[]> = {
  '/painel': ['/dashboard?scope=month'],
  '/clientes': ['/customers?page=1&per_page=20'],
  '/hidrometros': ['/hydrometers', '/customers/options?has_hydrometer=true&limit=1000'],
  '/leituras': ['/readings?status=pending&per_page=50'],
  '/faturas': ['/invoices?page=1&per_page=20'],
  '/conversas': ['/whatsapp/conversations'],
  '/tarifas': ['/tariffs'],
  '/notificacoes': ['/health', '/hydrometers/ocr-memory/summary', '/system-settings'],
  '/configuracoes': ['/deductions', '/health', '/system-settings'],
};

export const PRIMARY_DATA_PATHS = [
  ...ROUTE_DATA['/painel'],
  ...ROUTE_DATA['/clientes'],
  ...ROUTE_DATA['/faturas'],
];

export const SECONDARY_DATA_PATHS = Object.entries(ROUTE_DATA)
  .filter(([route]) => !['/painel', '/clientes', '/faturas'].includes(route))
  .flatMap(([, paths]) => paths);

export function prefetchRouteData(route: string): void {
  api.prefetch(ROUTE_DATA[route] || []);
}

