'use client';

/* eslint-disable react-hooks/set-state-in-effect */

import { useEffect, useState, FormEvent } from 'react';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { useAppFeedback } from '@/components/AppFeedbackProvider';
import { Droplets, Pencil, Plus, Search, Loader2, X, Printer, Power, RotateCcw, FileText } from 'lucide-react';

interface Customer {
  id: string;
  name: string;
  cpf_cnpj: string;
}

interface Hydrometer {
  id: string;
  code: string;
  qr_code_token: string;
  customer_id: string;
  brand: string;
  model: string;
  red_digits: number;
  black_digits: number | null;
  location_description: string;
  last_reading_value: number;
  last_reading_date: string;
  is_active: boolean;
  installed_at: string;
  disconnected_at: string | null;
  reconnected_at: string | null;
  disconnection_reason: string | null;
  customer?: Customer;
}

const STICKER_DIAMETER_MM = 45;
const STICKER_DESIGN_DIAMETER_MM = 90;

const escapeHtml = (value: string) => value
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#039;');

const buildStickerMarkup = (hydrometer: Hydrometer, qrDataUrl: string) => {
  const rawCustomerName = (hydrometer.customer?.name?.trim() || 'Cliente não identificado')
    .replace(/\s+/g, ' ');
  const customerName = escapeHtml(rawCustomerName);
  const longestNamePart = Math.max(...rawCustomerName.split(' ').map(part => part.length));
  const customerNameClass = rawCustomerName.length > 42 || longestNamePart > 18
    ? 'is-xlong'
    : rawCustomerName.length > 30 || longestNamePart > 14
      ? 'is-long'
      : rawCustomerName.length > 20
        ? 'is-medium'
        : '';

  return `
    <div class="sticker-slot">
      <article class="meter-sticker">
        <header class="sticker-brand">
          <div class="brand-mark" aria-hidden="true">
            <svg viewBox="0 0 64 76" role="img">
              <path d="M32 2C25 16 12 28 12 43c0 12 9 22 20 22s20-10 20-22C52 28 39 16 32 2Z" fill="#2e9fd0" />
              <path d="M21 46c2 6 6 10 13 11" fill="none" stroke="#ffffff" stroke-width="3.5" stroke-linecap="round" opacity=".9" />
              <path d="M8 68c7-4 13-4 20 0s13 4 28-1" fill="none" stroke="#0f4f86" stroke-width="4" stroke-linecap="round" />
              <path d="M12 74c7-3 13-3 19 0s12 3 21 0" fill="none" stroke="#2e9fd0" stroke-width="3" stroke-linecap="round" />
            </svg>
          </div>
          <div class="brand-copy">
            <strong>AQUAMOAB</strong>
            <span>SANEAMENTO</span>
          </div>
        </header>

        <div class="sticker-divider"></div>

        <section class="sticker-body">
          <div class="sticker-info">
            <div class="info-title">ACESSE SUAS<br />INFORMAÇÕES</div>

            <div class="info-row">
              <span class="info-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24">
                  <path d="M5 19V11M10 19V7M15 19v-5M20 19V4" />
                  <path d="M3 19h18" />
                </svg>
              </span>
              <span>Consumo<br />de água</span>
            </div>

            <div class="info-row">
              <span class="info-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24">
                  <path d="M6 3h9l3 3v15H6z" />
                  <path d="M15 3v4h4M9 11h6M9 15h6" />
                </svg>
              </span>
              <span>2ª via<br />de fatura</span>
            </div>

            <div class="info-row">
              <span class="info-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24">
                  <path d="M20 11a8 8 0 0 1-8 8 9 9 0 0 1-3-.5L4 21l1.5-4A8 8 0 1 1 20 11Z" />
                </svg>
              </span>
              <span>Avisos e<br />comunicados</span>
            </div>
          </div>

          <div class="qr-panel">
            <img src="${qrDataUrl}" alt="QR do hidrômetro ${escapeHtml(hydrometer.code)}" />
            <div class="qr-caption">
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <rect x="6" y="2.5" width="12" height="19" rx="2" />
                <path d="M10 5h4M11 18.5h2" />
              </svg>
              <span>APONTE A CÂMERA<br />DO SEU CELULAR</span>
            </div>
          </div>
        </section>

        <footer class="sticker-footer">
          <div class="customer-label">NOME DO CLIENTE</div>
          <div class="customer-name ${customerNameClass}">${customerName}</div>
          <div class="tagline">
            <svg viewBox="0 0 32 40" aria-hidden="true">
              <path d="M16 2C12 11 5 17 5 26a11 11 0 0 0 22 0c0-9-7-15-11-24Z" />
            </svg>
            <span>CADA GOTA IMPORTA</span>
          </div>
        </footer>
      </article>
    </div>
  `;
};

const buildStickerPrintDocument = (cards: string[], title: string, singleSticker: boolean) => `
  <!doctype html>
  <html lang="pt-BR">
    <head>
      <meta charset="utf-8" />
      <meta name="viewport" content="width=device-width, initial-scale=1" />
      <title>${escapeHtml(title)}</title>
      <style>
        :root {
          --brand: #0f4f86;
          --brand-dark: #0b355b;
          --accent: #2e9fd0;
          --soft-blue: #dcecf6;
          --sticker-size: ${STICKER_DIAMETER_MM}mm;
          --sticker-design-size: ${STICKER_DESIGN_DIAMETER_MM}mm;
          --sticker-scale: ${STICKER_DIAMETER_MM / STICKER_DESIGN_DIAMETER_MM};
        }

        @page { size: A4; margin: 5mm; }
        * { box-sizing: border-box; }

        body {
          margin: 0;
          background: #ffffff;
          color: var(--brand-dark);
          font-family: Arial, Helvetica, sans-serif;
        }

        .sheet {
          display: grid;
          grid-template-columns: repeat(4, var(--sticker-size));
          grid-auto-rows: var(--sticker-size);
          justify-content: center;
          align-content: start;
          gap: 3mm;
        }

        .sheet.single {
          grid-template-columns: var(--sticker-size);
        }

        .sticker-slot {
          position: relative;
          width: var(--sticker-size);
          height: var(--sticker-size);
          overflow: visible;
          break-inside: avoid;
          page-break-inside: avoid;
        }

        .meter-sticker {
          position: relative;
          isolation: isolate;
          width: var(--sticker-design-size);
          height: var(--sticker-design-size);
          padding: 6.5mm 7mm 5.5mm;
          overflow: hidden;
          display: flex;
          flex-direction: column;
          border: .65mm solid var(--brand);
          border-radius: 50%;
          background: #ffffff;
          transform: scale(var(--sticker-scale));
          transform-origin: top left;
        }

        .meter-sticker::after {
          content: '';
          position: absolute;
          z-index: -1;
          inset: 1.5mm;
          border: .2mm solid #b7d3e7;
          border-radius: 50%;
          pointer-events: none;
        }

        .sticker-brand {
          flex: none;
          height: 11.5mm;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 2.2mm;
        }

        .brand-mark {
          width: 9.5mm;
          height: 10.5mm;
          flex: none;
        }

        .brand-mark svg {
          display: block;
          width: 100%;
          height: 100%;
        }

        .brand-copy {
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          line-height: 1;
        }

        .brand-copy strong {
          color: var(--brand);
          font-size: 5mm;
          font-weight: 800;
          letter-spacing: -.18mm;
        }

        .brand-copy span {
          margin-top: 1.1mm;
          color: var(--brand-dark);
          font-size: 2.15mm;
          letter-spacing: 1.2mm;
        }

        .sticker-divider {
          flex: none;
          height: .45mm;
          margin: 1.3mm 2mm 0;
          background: var(--brand);
          border-radius: 10mm;
        }

        .sticker-body {
          flex: 1;
          min-height: 0;
          display: grid;
          grid-template-columns: minmax(0, 1fr) 31mm;
          align-items: center;
          gap: 3mm;
          padding: 2.5mm 0 2mm;
        }

        .sticker-info {
          min-width: 0;
          padding-left: 1mm;
        }

        .info-title {
          margin-bottom: 1.8mm;
          color: var(--brand);
          font-size: 3.6mm;
          font-weight: 800;
          line-height: 1.12;
        }

        .info-row {
          display: grid;
          grid-template-columns: 7mm minmax(0, 1fr);
          align-items: center;
          gap: 1.5mm;
          margin-top: 1.4mm;
          color: #132d43;
          font-size: 2.8mm;
          font-weight: 650;
          line-height: 1.08;
        }

        .info-icon {
          width: 7mm;
          height: 7mm;
          display: grid;
          place-items: center;
          border: .45mm solid var(--brand);
          border-radius: 50%;
          color: var(--brand);
        }

        .info-icon svg {
          width: 4.4mm;
          height: 4.4mm;
          fill: none;
          stroke: currentColor;
          stroke-width: 1.7;
          stroke-linecap: round;
          stroke-linejoin: round;
        }

        .qr-panel {
          align-self: center;
          width: 31mm;
          padding: 1.1mm;
          overflow: hidden;
          border: .55mm solid var(--brand);
          border-radius: 3.2mm;
          background: #ffffff;
        }

        .qr-panel > img {
          display: block;
          width: 27.7mm;
          height: 27.7mm;
          margin: 0 auto;
        }

        .qr-caption {
          min-height: 7.3mm;
          margin-top: .9mm;
          padding: .75mm .6mm;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: .8mm;
          border-radius: 1.4mm;
          background: var(--brand);
          color: #ffffff;
          font-size: 2.05mm;
          font-weight: 800;
          line-height: 1.05;
          text-align: left;
        }

        .qr-caption svg {
          width: 4.4mm;
          height: 4.4mm;
          flex: none;
          fill: none;
          stroke: currentColor;
          stroke-width: 1.7;
          stroke-linecap: round;
          stroke-linejoin: round;
        }

        .sticker-footer {
          flex: none;
          margin: 0 3mm;
          padding-top: 1.5mm;
          border-top: .45mm solid var(--brand);
          text-align: center;
        }

        .customer-label {
          color: var(--brand);
          font-size: 2.3mm;
          font-weight: 700;
          letter-spacing: .25mm;
        }

        .customer-name {
          width: 100%;
          min-height: 8mm;
          max-height: 10mm;
          margin: .7mm auto 0;
          padding: 0 1mm;
          display: grid;
          place-items: center;
          overflow: hidden;
          overflow-wrap: anywhere;
          word-break: normal;
          hyphens: auto;
          color: var(--brand-dark);
          font-size: 4.15mm;
          font-weight: 800;
          line-height: 1;
          text-align: center;
          text-transform: uppercase;
        }

        .customer-name.is-medium { font-size: 3.5mm; line-height: 1.04; }
        .customer-name.is-long { font-size: 2.9mm; line-height: 1.08; }
        .customer-name.is-xlong { font-size: 2.45mm; line-height: 1.08; letter-spacing: -.04mm; }

        .tagline {
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 1mm;
          color: var(--brand);
          font-size: 2.45mm;
          letter-spacing: .35mm;
        }

        .tagline svg {
          width: 3.5mm;
          height: 4.3mm;
          fill: var(--accent);
        }

        @media screen {
          body {
            min-height: 100vh;
            padding: 8mm;
            background: #edf4f8;
          }

          .meter-sticker {
            box-shadow: 0 3mm 8mm rgba(15, 79, 134, .16);
          }
        }

        @media print {
          body {
            -webkit-print-color-adjust: exact;
            print-color-adjust: exact;
          }
        }
      </style>
    </head>
    <body>
      <main class="sheet${singleSticker ? ' single' : ''}">${cards.join('')}</main>
      <script>
        window.onload = () => {
          window.setTimeout(() => {
            window.focus();
            window.print();
          }, 120);
        };
      </script>
    </body>
  </html>
`;

export default function HydrometersPage() {
  const { notify } = useAppFeedback();
  const [items, setItems] = useState<Hydrometer[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<Hydrometer | null>(null);
  const [saving, setSaving] = useState(false);
  const [search, setSearch] = useState('');

  const [form, setForm] = useState({
    customer_id: '',
    code: '',
    brand: '',
    model: '',
    red_digits: 3,
    black_digits: '',
    location_description: '',
    initial_reading: 0,
  });

  const load = () => {
    setLoading(true);
    api.get<{ items: Hydrometer[] }>('/hydrometers')
      .then(r => setItems(r.items))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  const loadCustomers = () => {
    api.get<{ items: Customer[] }>('/customers/options?has_hydrometer=true&limit=1000')
      .then(r => setCustomers(r.items))
      .catch(console.error);
  };

  useEffect(() => {
    load();
    loadCustomers();
  }, []);

  const handleAdd = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.post('/hydrometers', {
        customer_id: form.customer_id,
        code: form.code.toUpperCase() || null,
        brand: form.brand || null,
        model: form.model || null,
        red_digits: form.red_digits,
        black_digits: form.black_digits === '' ? null : Number(form.black_digits),
        location_description: form.location_description || null,
        initial_reading: form.initial_reading,
      });
      setShowAdd(false);
      setForm({ customer_id: '', code: '', brand: '', model: '', red_digits: 3, black_digits: '', location_description: '', initial_reading: 0 });
      load();
      notify('Hidrômetro associado', 'O medidor foi vinculado com sucesso.', 'success');
    } catch (err: unknown) {
      notify('Falha ao associar hidrômetro', err instanceof Error ? err.message : 'Erro ao criar hidrômetro.', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = async (e: FormEvent) => {
    e.preventDefault();
    if (!editing) return;
    setSaving(true);
    try {
      await api.patch(`/hydrometers/${editing.id}`, {
        code: editing.code || null,
        brand: editing.brand || null,
        model: editing.model || null,
        red_digits: editing.red_digits,
        black_digits: editing.black_digits || null,
        location_description: editing.location_description || null,
        last_reading_value: editing.last_reading_value,
        is_active: editing.is_active,
      });
      setEditing(null);
      load();
      notify('Hidrômetro atualizado', 'As informações do medidor foram salvas.', 'success');
    } catch (err: unknown) {
      notify('Falha ao editar hidrômetro', err instanceof Error ? err.message : 'Erro ao salvar hidrômetro.', 'error');
    } finally {
      setSaving(false);
    }
  };

  const filteredItems = items.filter(h =>
    h.code.toLowerCase().includes(search.toLowerCase()) ||
    h.customer?.name.toLowerCase().includes(search.toLowerCase())
  );
  const activeCount = items.filter(h => h.is_active).length;
  const inactiveCount = items.length - activeCount;
  const countSubtitle = search.trim()
    ? `${filteredItems.length} encontrados de ${items.length} medidores · ${activeCount} ativos · ${inactiveCount} inativos`
    : `${items.length} medidores · ${activeCount} ativos · ${inactiveCount} inativos`;

  const openStickerPrintWindow = async (
    hydrometers: Hydrometer[],
    title: string,
    singleSticker = false,
  ) => {
    const printWindow = window.open('', '_blank');
    if (!printWindow) {
      notify('Pop-up bloqueado', 'Permita pop-ups para abrir as etiquetas dos hidrômetros.', 'warning');
      return;
    }

    printWindow.document.write('<!doctype html><html><head><title>Etiquetas AquaMoab</title></head><body><p>Gerando etiquetas...</p></body></html>');

    try {
      const QRCode = await import('qrcode');
      const cards = await Promise.all(hydrometers.map(async hydrometer => {
        const qrValue = hydrometer.qr_code_token || hydrometer.code;
        const qrDataUrl = await QRCode.toDataURL(qrValue, {
          margin: 2,
          width: 420,
          errorCorrectionLevel: 'M',
        });
        return buildStickerMarkup(hydrometer, qrDataUrl);
      }));

      printWindow.document.open();
      printWindow.document.write(buildStickerPrintDocument(cards, title, singleSticker));
      printWindow.document.close();
    } catch (err: unknown) {
      printWindow.close();
      notify('Falha ao gerar etiquetas', err instanceof Error ? err.message : 'Nao foi possivel montar as etiquetas dos hidrômetros.', 'error');
    }
  };

  const printQrSticker = async (hydrometer: Hydrometer) => {
    const customerName = hydrometer.customer?.name || hydrometer.code;
    await openStickerPrintWindow([hydrometer], `Etiqueta - ${customerName}`, true);
  };

  const generateQrPdf = async () => {
    const hydrometers = search.trim() ? filteredItems : items;
    if (!hydrometers.length) {
      notify('Nenhuma etiqueta para gerar', 'Cadastre um hidrômetro ou ajuste a busca antes de gerar as etiquetas.', 'warning');
      return;
    }

    await openStickerPrintWindow(hydrometers, 'Etiquetas de hidrômetros AquaMoab');
  };

  const disconnectHydrometer = async (hydrometer: Hydrometer) => {
    setSaving(true);
    try {
      await api.post(`/hydrometers/${hydrometer.id}/disconnect`, { reason: 'Falta de pagamento' });
      load();
      notify('Hidrômetro desligado', 'O cliente foi marcado como desligado.', 'warning');
    } catch (err: unknown) {
      notify('Falha ao desligar', err instanceof Error ? err.message : 'Erro ao desligar hidrômetro.', 'error');
    } finally {
      setSaving(false);
    }
  };

  const reconnectHydrometer = async (hydrometer: Hydrometer) => {
    setSaving(true);
    try {
      await api.post(`/hydrometers/${hydrometer.id}/reconnect`);
      load();
      notify('Religamento registrado', 'O hidrômetro foi ativado e a taxa de religamento foi gerada.', 'success');
    } catch (err: unknown) {
      notify('Falha ao religar', err instanceof Error ? err.message : 'Erro ao religar hidrômetro.', 'error');
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Header title="Hidrômetros" subtitle={countSubtitle} />

      <div className="toolbar">
        <div className="search-box">
          <Search />
          <input
            placeholder="Buscar por código ou cliente..."
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
          <Plus size={16} /> Associar Novo Hidrômetro
        </button>
        <button className="btn btn-secondary" onClick={generateQrPdf} disabled={loading || !items.length}>
          <FileText size={16} /> Etiquetas para hidrômetros
        </button>
      </div>

      <div className="table-wrapper">
        <table className="data-table">
          <thead>
            <tr>
              <th>Código / Cliente</th>
              <th>Marca/Modelo</th>
              <th>Mostrador</th>
              <th>Local</th>
              <th>Última Leitura</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              [...Array(5)].map((_, i) => (
                <tr key={i}>
                  <td><div className="skeleton" style={{ height: 20, width: '90%' }} /></td>
                  <td><div className="skeleton" style={{ height: 20, width: '60%' }} /></td>
                  <td><div className="skeleton" style={{ height: 20, width: '70%' }} /></td>
                  <td><div className="skeleton" style={{ height: 20, width: '40%' }} /></td>
                  <td><div className="skeleton" style={{ height: 24, width: 60, borderRadius: 99 }} /></td>
                </tr>
              ))
            ) : !filteredItems.length ? (
              <tr><td colSpan={7}><div className="empty-state"><Droplets /><p>Nenhum hidrômetro encontrado</p></div></td></tr>
            ) : filteredItems.map(h => (
              <tr key={h.id}>
                <td>
                  <div className="cell-primary" style={{ fontWeight: 800 }}>QR {h.code}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{h.customer?.name || 'Cliente desconhecido'}</div>
                </td>
                <td>{[h.brand, h.model].filter(Boolean).join(' ') || '—'}</td>
                <td>{h.red_digits || 3} vermelhos{h.black_digits ? ` · ${h.black_digits} pretos` : ''}</td>
                <td>{h.location_description || '—'}</td>
                <td>
                  <span style={{ fontWeight: 600 }}>{h.last_reading_value.toFixed(2)} m³</span>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {h.last_reading_date ? new Date(h.last_reading_date).toLocaleDateString('pt-BR') : 'Sem leituras'}
                  </div>
                </td>
                <td><span className={`badge ${h.is_active ? 'active' : 'suspended'}`}>{h.is_active ? 'Ativo' : 'Inativo'}</span></td>
                <td>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn btn-ghost btn-icon btn-sm" onClick={() => printQrSticker(h)} title="Imprimir etiqueta do hidrômetro">
                      <Printer size={14} />
                    </button>
                    {h.is_active ? (
                      <button className="btn btn-ghost btn-icon btn-sm" onClick={() => disconnectHydrometer(h)} title="Desligar hidrômetro" disabled={saving}>
                        <Power size={14} />
                      </button>
                    ) : (
                      <button className="btn btn-ghost btn-icon btn-sm" onClick={() => reconnectHydrometer(h)} title="Religar hidrômetro" disabled={saving}>
                        <RotateCcw size={14} />
                      </button>
                    )}
                    <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setEditing(h)} title="Editar hidrômetro">
                      <Pencil size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showAdd && (
        <div className="modal-overlay">
          <div className="modal">
            <div className="modal-header">
              <h2 className="modal-title">Associar Hidrômetro</h2>
              <button className="btn btn-ghost btn-icon" onClick={() => setShowAdd(false)}><X size={20} /></button>
            </div>
            <form onSubmit={handleAdd}>
              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Cliente Responsável</label>
                <select
                  className="form-select"
                  value={form.customer_id}
                  onChange={e => setForm({ ...form, customer_id: e.target.value })}
                  required
                >
                  <option value="">Selecione um cliente com perfil de medição...</option>
                  {customers.map(c => (
                    <option key={c.id} value={c.id}>{c.name} (CPF/CNPJ: {c.cpf_cnpj})</option>
                  ))}
                </select>
              </div>

              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Código do Hidrômetro (números)</label>
                <input
                  className="form-input"
                  placeholder="Ex: 000123 (deixe em branco para gerar)"
                  value={form.code}
                  onChange={e => setForm({ ...form, code: e.target.value.replace(/\D/g, '') })}
                  inputMode="numeric"
                  maxLength={12}
                />
              </div>

              <div className="form-grid" style={{ marginBottom: 16 }}>
                <div className="form-group">
                  <label className="form-label">Marca (Opcional)</label>
                  <input className="form-input" value={form.brand} onChange={e => setForm({ ...form, brand: e.target.value })} />
                </div>
                <div className="form-group">
                  <label className="form-label">Modelo (Opcional)</label>
                  <input className="form-input" value={form.model} onChange={e => setForm({ ...form, model: e.target.value })} />
                </div>
              </div>

              <div className="form-grid" style={{ marginBottom: 16 }}>
                <div className="form-group">
                  <label className="form-label">Dígitos vermelhos</label>
                  <select className="form-select" value={form.red_digits} onChange={e => setForm({ ...form, red_digits: Number(e.target.value) })}>
                    <option value={2}>2 dígitos vermelhos</option>
                    <option value={3}>3 dígitos vermelhos</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Dígitos pretos</label>
                  <input className="form-input" type="number" min={1} value={form.black_digits} onChange={e => setForm({ ...form, black_digits: e.target.value })} placeholder="Opcional" />
                </div>
              </div>

              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Localização no Imóvel (Opcional)</label>
                <input className="form-input" placeholder="Ex: Muro frontal esquerdo" value={form.location_description} onChange={e => setForm({ ...form, location_description: e.target.value })} />
              </div>

              <div className="form-group" style={{ marginBottom: 24 }}>
                <label className="form-label">Leitura Inicial (m³)</label>
                <input className="form-input" type="number" step="0.001" min="0" value={form.initial_reading} onChange={e => setForm({ ...form, initial_reading: parseFloat(e.target.value) })} required />
              </div>

              <div className="modal-footer">
                <button type="button" className="btn btn-ghost" onClick={() => setShowAdd(false)}>Cancelar</button>
                <button type="submit" className="btn btn-primary" disabled={saving || !form.customer_id}>
                  {saving ? <Loader2 size={16} className="spinner" /> : 'Associar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {editing && (
        <div className="modal-overlay">
          <div className="modal">
            <div className="modal-header">
              <h2 className="modal-title">Editar Hidrômetro</h2>
              <button className="btn btn-ghost btn-icon" onClick={() => setEditing(null)}><X size={20} /></button>
            </div>
            <form onSubmit={handleEdit}>
              <div className="form-grid" style={{ marginBottom: 16 }}>
                <div className="form-group">
                  <label className="form-label">Código numérico</label>
                  <input className="form-input" value={editing.code} onChange={e => setEditing({ ...editing, code: e.target.value.replace(/\D/g, '') })} inputMode="numeric" />
                </div>
                <div className="form-group">
                  <label className="form-label">Última leitura base</label>
                  <input className="form-input" type="number" step="0.001" min="0" value={editing.last_reading_value} onChange={e => setEditing({ ...editing, last_reading_value: parseFloat(e.target.value) || 0 })} />
                </div>
              </div>
              <div className="form-grid" style={{ marginBottom: 16 }}>
                <div className="form-group">
                  <label className="form-label">Marca</label>
                  <input className="form-input" value={editing.brand || ''} onChange={e => setEditing({ ...editing, brand: e.target.value })} />
                </div>
                <div className="form-group">
                  <label className="form-label">Modelo</label>
                  <input className="form-input" value={editing.model || ''} onChange={e => setEditing({ ...editing, model: e.target.value })} />
                </div>
              </div>
              <div className="form-grid" style={{ marginBottom: 16 }}>
                <div className="form-group">
                  <label className="form-label">Dígitos vermelhos</label>
                  <select className="form-select" value={editing.red_digits || 3} onChange={e => setEditing({ ...editing, red_digits: Number(e.target.value) })}>
                    <option value={2}>2 dígitos vermelhos</option>
                    <option value={3}>3 dígitos vermelhos</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Dígitos pretos</label>
                  <input className="form-input" type="number" min={1} value={editing.black_digits || ''} onChange={e => setEditing({ ...editing, black_digits: e.target.value ? Number(e.target.value) : null })} placeholder="Opcional" />
                </div>
              </div>
              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Localização</label>
                <input className="form-input" value={editing.location_description || ''} onChange={e => setEditing({ ...editing, location_description: e.target.value })} />
              </div>
              <div className="form-group" style={{ marginBottom: 24 }}>
                <label className="form-label">Status</label>
                <select className="form-select" value={editing.is_active ? 'true' : 'false'} onChange={e => setEditing({ ...editing, is_active: e.target.value === 'true' })}>
                  <option value="true">Ativo</option>
                  <option value="false">Inativo</option>
                </select>
              </div>
              <div className="modal-footer">
                <button type="button" className="btn btn-ghost" onClick={() => setEditing(null)}>Cancelar</button>
                <button type="submit" className="btn btn-primary" disabled={saving}>
                  {saving ? <Loader2 size={16} className="spinner" /> : 'Salvar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </>
  );
}
