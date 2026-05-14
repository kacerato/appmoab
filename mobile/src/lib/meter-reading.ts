export function parseMeterReadingInput(input: string, redDigits: number): number | null {
  const trimmed = input.trim().replace(',', '.');
  if (!trimmed) return null;

  if (trimmed.includes('.')) {
    const parsed = Number(trimmed);
    return Number.isFinite(parsed) ? parsed : null;
  }

  const digits = trimmed.replace(/\D/g, '');
  if (!digits) return null;

  const safeRedDigits = redDigits > 0 ? redDigits : 0;
  const rawValue = Number(digits);
  if (!Number.isFinite(rawValue)) return null;

  return safeRedDigits > 0 ? rawValue / (10 ** safeRedDigits) : rawValue;
}

export function formatMeterReading(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '--';
  return value.toLocaleString('pt-BR', {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  });
}
