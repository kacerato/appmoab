'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';
import { Loader2, X } from 'lucide-react';
import { api } from '@/lib/api';
import { fileToDataUrl } from '@/lib/file-base64';

interface Context {
  hydrometer_id: string;
  cycle_id: string;
  reference_month: string;
  due_date: string;
  previous_value: number;
  previous_date: string;
}

interface Preview {
  previous_value: number;
  current_value: number;
  consumption_m3: number;
  amount: number;
  reference_month: string;
  due_date: string;
  payment_due_date: string;
  minimum_applied: boolean;
  high_consumption: boolean;
  validation_flags: { code: string; label: string; message: string; severity: string }[];
}

interface Result {
  invoice_id: string;
  boleto_status: string;
}

const m3 = (value: number) => value.toLocaleString('pt-BR', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const money = (value: number) => new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(value);
const dateLabel = (value: string) => value.split('-').reverse().join('/');
const today = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'America/Fortaleza' }).format(new Date());

export default function ManualReadingModal({ hydrometer, onClose, onSaved }: {
  hydrometer: { id: string; code: string; red_digits: number | null };
  onClose: () => void;
  onSaved: (result: Result) => void;
}) {
  const [context, setContext] = useState<Context | null>(null);
  const [value, setValue] = useState('');
  const [readingDate, setReadingDate] = useState(today);
  const [reason, setReason] = useState('Leitura informada pelo cliente');
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const submitting = useRef(false);
  const parsed = Number(value.trim().replace(',', '.'));
  const valid = /^\d+(?:[.,]\d{1,3})?$/.test(value.trim()) && Number.isFinite(parsed);

  useEffect(() => {
    let active = true;
    api.get<Context>(`/readings/manual-context?hydrometer_id=${hydrometer.id}`, { skipCache: true })
      .then(result => { if (active) setContext(result); })
      .catch(err => { if (active) setError(err instanceof Error ? err.message : 'Não foi possível abrir o lançamento.'); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [hydrometer.id]);

  const resetPreview = () => { setPreview(null); setAcknowledged(false); setError(''); };
  const payload = () => ({
    hydrometer_id: hydrometer.id,
    cycle_id: context!.cycle_id,
    expected_previous_value: context!.previous_value,
    current_value: parsed,
    reading_date: readingDate,
    reason: reason.trim(),
    acknowledge_high_consumption: acknowledged,
  });

  const calculate = async () => {
    if (!context || !valid || reason.trim().length < 5 || busy) return;
    setBusy(true);
    setError('');
    try {
      setPreview(await api.post<Preview>('/readings/manual/preview', payload()));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Não foi possível calcular o consumo.');
    } finally { setBusy(false); }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!preview || !context || !valid || submitting.current || (preview.high_consumption && !acknowledged)) return;
    submitting.current = true;
    setBusy(true);
    setError('');
    try {
      const photo = file ? await fileToDataUrl(file) : null;
      const result = await api.post<Result>('/readings/manual', { ...payload(), expected_amount: preview.amount, photo_base64: photo });
      onSaved(result);
    } catch (err) {
      setError(`${err instanceof Error ? err.message : 'Não foi possível confirmar.'} Se houve demora na emissão, confira o histórico de faturas antes de tentar novamente.`);
    } finally { submitting.current = false; setBusy(false); }
  };

  return (
    <div className="modal-overlay" onClick={() => { if (!busy) onClose(); }}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="manual-reading-title" style={{ maxWidth: 580 }} onClick={event => event.stopPropagation()}>
        <div className="modal-header">
          <div><h2 id="manual-reading-title" className="modal-title">Registrar leitura manual</h2><p style={{ color: 'var(--text-muted)', fontSize: 13 }}>Hidrômetro {hydrometer.code} · Leitura informada pelo cliente</p></div>
          <button className="btn btn-ghost" aria-label="Fechar lançamento manual" onClick={onClose} disabled={busy}><X size={18} /></button>
        </div>
        <form onSubmit={submit}>
          <div className="modal-body" style={{ display: 'grid', gap: 16 }}>
            {loading && <p><Loader2 size={16} className="spinner" /> Carregando o ciclo de leitura…</p>}
            {error && <div role="alert" style={{ color: 'var(--danger)', padding: 12, border: '1px solid var(--border)', borderRadius: 8 }}>{error}</div>}
            {context && <>
              <div style={{ background: 'var(--accent-soft)', padding: 14, borderRadius: 8 }}>
                <strong>Leitura anterior: {m3(context.previous_value)} m³</strong>
                <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 4 }}>{dateLabel(context.previous_date)} · Competência {context.reference_month} · Vencimento {dateLabel(context.due_date)}</div>
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="manual-reading-value">Leitura atual em m³</label>
                <input id="manual-reading-value" className="form-input" inputMode="decimal" value={value} onChange={event => { setValue(event.target.value); resetPreview(); }} placeholder="Ex.: 135,000" required disabled={busy} />
                <small style={{ color: 'var(--text-muted)' }}>Digite o número do visor em m³, incluindo os decimais. Ex.: 135,250 significa 135 m³ e 250 litros.</small>
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="manual-reading-date">Data em que o cliente verificou o hidrômetro</label>
                <input id="manual-reading-date" className="form-input" type="date" max={today()} value={readingDate} onChange={event => { setReadingDate(event.target.value); resetPreview(); }} required disabled={busy} />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="manual-reading-reason">Motivo / observação</label>
                <textarea id="manual-reading-reason" className="form-input" value={reason} minLength={5} maxLength={500} rows={2} onChange={event => { setReason(event.target.value); resetPreview(); }} required disabled={busy} />
              </div>
              <div className="form-group">
                <label className="form-label" htmlFor="manual-reading-photo">Foto enviada pelo cliente (opcional)</label>
                <input id="manual-reading-photo" className="form-input" type="file" accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={event => {
                  const selected = event.target.files?.[0] || null;
                  if (selected && (selected.size > 8 * 1024 * 1024 || !['image/jpeg', 'image/png', 'image/webp'].includes(selected.type))) {
                    setError('Escolha uma imagem JPG, PNG ou WebP de até 8 MB.'); event.target.value = ''; setFile(null); return;
                  }
                  setFile(selected); setError('');
                }} />
              </div>
              {preview && <div style={{ border: '1px solid var(--border)', borderRadius: 8, padding: 16 }}>
                <strong>Confira antes de confirmar</strong>
                <dl style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 8, margin: '12px 0' }}>
                  <dt>Leitura anterior</dt><dd>{m3(preview.previous_value)} m³</dd>
                  <dt>Leitura atual / próxima base</dt><dd>{m3(preview.current_value)} m³</dd>
                  <dt>Consumo a cobrar</dt><dd><strong>{m3(preview.consumption_m3)} m³</strong></dd>
                  <dt>Valor da cobrança</dt><dd><strong>{money(preview.amount)}</strong></dd>
                  <dt>Competência</dt><dd>{preview.reference_month}</dd>
                  <dt>Vencimento do boleto</dt><dd>{dateLabel(preview.payment_due_date)}</dd>
                </dl>
                {preview.minimum_applied && <p style={{ fontSize: 12 }}>Aplicada a cobrança mínima da tarifa configurada.</p>}
                {preview.payment_due_date !== preview.due_date && <p style={{ fontSize: 12 }}>O vencimento original da competência é {dateLabel(preview.due_date)}. O boleto terá prazo atualizado, sem multa ou juros por atraso operacional da leitura.</p>}
                {preview.validation_flags.filter(flag => flag.code !== 'manual_customer_report').map(flag => <p key={flag.code} style={{ fontSize: 13 }}>{flag.label}: {flag.message}</p>)}
                {preview.high_consumption && <label style={{ display: 'flex', gap: 8, marginTop: 12 }}><input type="checkbox" checked={acknowledged} onChange={event => setAcknowledged(event.target.checked)} disabled={busy} />Conferi o valor informado e confirmo o consumo elevado.</label>}
                <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 12 }}>A confirmação registra uma nova leitura, gera a fatura e conclui este ciclo. A próxima leitura parte do valor informado.</p>
              </div>}
            </>}
          </div>
          <div className="modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={busy}>Fechar</button>
            {context && (!preview ? <button type="button" className="btn btn-primary" onClick={calculate} disabled={busy || !valid || reason.trim().length < 5 || !readingDate}>{busy ? <Loader2 size={16} className="spinner" /> : 'Calcular e conferir'}</button> :
              <button type="submit" className="btn btn-primary" disabled={busy || (preview.high_consumption && !acknowledged)}>{busy ? <><Loader2 size={16} className="spinner" /> Registrando…</> : 'Confirmar leitura e gerar cobrança'}</button>)}
          </div>
        </form>
      </div>
    </div>
  );
}
