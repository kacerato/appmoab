'use client';

/* eslint-disable react-hooks/set-state-in-effect */

import { useEffect, useState, FormEvent } from 'react';
import { api } from '@/lib/api';
import Header from '@/components/Header';
import { useAppFeedback } from '@/components/AppFeedbackProvider';
import {
  Droplets,
  Pencil,
  Plus,
  Search,
  Loader2,
  X,
  Printer,
  FileDown,
  Power,
  RotateCcw,
} from 'lucide-react';

interface Customer {
  id: string;
  name: string;
  cpf_cnpj: string;
  has_hydrometer: boolean;
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

interface PdfJpegPage {
  bytes: Uint8Array;
  width: number;
  height: number;
}

type ReconnectMode = 'reading_only' | 'with_fee';

const STICKER_DIAMETER_MM = 45;
const STICKER_DESIGN_DIAMETER_MM = 90;
const STICKERS_PER_ROW = 4;
const STICKER_ROWS_PER_PAGE = 6;
const STICKER_GAP_MM = 3;
const PDF_DPI = 300;
const STICKER_RENDER_SIZE_PX = 900;
const COMPANY_NAME = 'MAR AZUL SERVIÇOS';
const COMPANY_SUBTITLE = 'DISTRIBUIÇÃO DE ÁGUA';

const escapeHtml = (value: string) => value
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;')
  .replace(/'/g, '&#039;');

const sanitizeFileName = (value: string) => value
  .normalize('NFD')
  .replace(/[\u0300-\u036f]/g, '')
  .replace(/[^a-zA-Z0-9]+/g, '-')
  .replace(/^-+|-+$/g, '')
  .toLowerCase() || 'etiqueta';

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
            <strong>${COMPANY_NAME}</strong>
            <span>${COMPANY_SUBTITLE}</span>
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

const buildStickerDocument = (
  cards: string[],
  title: string,
  singleSticker: boolean,
  autoPrint = true,
) => `
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
          grid-template-columns: repeat(${STICKERS_PER_ROW}, var(--sticker-size));
          grid-auto-rows: var(--sticker-size);
          justify-content: center;
          align-content: start;
          gap: ${STICKER_GAP_MM}mm;
        }

        .sheet.single { grid-template-columns: var(--sticker-size); }

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
          gap: 1.7mm;
        }

        .brand-mark {
          width: 8.5mm;
          height: 9.5mm;
          flex: none;
        }

        .brand-mark svg,
        .info-icon svg,
        .qr-caption svg {
          display: block;
          width: 100%;
          height: 100%;
        }

        .brand-copy {
          min-width: 0;
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          line-height: 1;
        }

        .brand-copy strong {
          color: var(--brand);
          font-size: 3.65mm;
          font-weight: 800;
          letter-spacing: -.12mm;
          white-space: nowrap;
        }

        .brand-copy span {
          margin-top: 1.15mm;
          color: var(--brand-dark);
          font-size: 1.65mm;
          font-weight: 700;
          letter-spacing: .38mm;
          white-space: nowrap;
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

        .sticker-info { min-width: 0; padding-left: 1mm; }

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
          padding: 1.1mm;
          border: .45mm solid var(--brand);
          border-radius: 50%;
          color: var(--brand);
        }

        .info-icon svg,
        .qr-caption svg {
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

        .qr-caption svg { width: 4.4mm; height: 4.4mm; flex: none; }

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

        .tagline svg { width: 3.5mm; height: 4.3mm; fill: var(--accent); }

        @media screen {
          body { min-height: 100vh; padding: 8mm; background: #edf4f8; }
          .meter-sticker { box-shadow: 0 3mm 8mm rgba(15, 79, 134, .16); }
        }

        @media print {
          body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
        }
      </style>
    </head>
    <body>
      <main class="sheet${singleSticker ? ' single' : ''}">${cards.join('')}</main>
      ${autoPrint ? `
        <script>
          window.onload = () => {
            window.setTimeout(() => {
              window.focus();
              window.print();
            }, 120);
          };
        </script>
      ` : ''}
    </body>
  </html>
`;

const textBytes = (value: string) => new TextEncoder().encode(value);

const dataUrlToBytes = (dataUrl: string) => {
  const base64 = dataUrl.split(',')[1] || '';
  const binary = window.atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
};

const buildPdfBlob = (pages: PdfJpegPage[]) => {
  const pageWidth = 595.28;
  const pageHeight = 841.89;
  const maxObjectId = 2 + pages.length * 3;
  const chunks: Uint8Array[] = [];
  const offsets = new Array<number>(maxObjectId + 1).fill(0);
  let byteOffset = 0;

  const push = (bytes: Uint8Array) => {
    chunks.push(bytes);
    byteOffset += bytes.length;
  };

  const pushText = (value: string) => push(textBytes(value));

  const addObject = (objectId: number, parts: Array<string | Uint8Array>) => {
    offsets[objectId] = byteOffset;
    pushText(`${objectId} 0 obj\n`);
    parts.forEach(part => typeof part === 'string' ? pushText(part) : push(part));
    pushText('\nendobj\n');
  };

  pushText('%PDF-1.4\n% Mar Azul Servicos\n');
  addObject(1, ['<< /Type /Catalog /Pages 2 0 R >>']);

  const pageObjectIds = pages.map((_, index) => 3 + index * 3);
  addObject(2, [`<< /Type /Pages /Kids [${pageObjectIds.map(id => `${id} 0 R`).join(' ')}] /Count ${pages.length} >>`]);

  pages.forEach((page, index) => {
    const pageObjectId = 3 + index * 3;
    const imageObjectId = pageObjectId + 1;
    const contentObjectId = pageObjectId + 2;
    const content = `q\n${pageWidth} 0 0 ${pageHeight} 0 0 cm\n/Im0 Do\nQ\n`;

    addObject(pageObjectId, [
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageWidth} ${pageHeight}] `,
      `/Resources << /XObject << /Im0 ${imageObjectId} 0 R >> >> `,
      `/Contents ${contentObjectId} 0 R >>`,
    ]);

    addObject(imageObjectId, [
      `<< /Type /XObject /Subtype /Image /Width ${page.width} /Height ${page.height} `,
      `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${page.bytes.length} >>\nstream\n`,
      page.bytes,
      '\nendstream',
    ]);

    addObject(contentObjectId, [
      `<< /Length ${textBytes(content).length} >>\nstream\n${content}endstream`,
    ]);
  });

  const xrefOffset = byteOffset;
  pushText(`xref\n0 ${maxObjectId + 1}\n`);
  pushText('0000000000 65535 f \n');
  for (let objectId = 1; objectId <= maxObjectId; objectId += 1) {
    pushText(`${String(offsets[objectId]).padStart(10, '0')} 00000 n \n`);
  }
  pushText(`trailer\n<< /Size ${maxObjectId + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`);

  return new Blob(chunks, { type: 'application/pdf' });
};

const waitForDocumentImages = async (documentRef: Document) => {
  await Promise.all(Array.from(documentRef.images).map(image => {
    if (image.complete && image.naturalWidth > 0) return Promise.resolve();
    return new Promise<void>((resolve, reject) => {
      image.onload = () => resolve();
      image.onerror = () => reject(new Error('Falha ao carregar uma imagem da etiqueta.'));
    });
  }));
};

const renderStickerSlot = async (slot: HTMLElement) => {
  const bounds = slot.getBoundingClientRect();
  if (!bounds.width || !bounds.height) {
    throw new Error('A etiqueta não possui dimensões válidas para gerar o PDF.');
  }

  const { default: html2canvas } = await import('html2canvas');
  return html2canvas(slot, {
    backgroundColor: '#ffffff',
    scale: STICKER_RENDER_SIZE_PX / bounds.width,
    useCORS: true,
    allowTaint: false,
    logging: false,
    width: bounds.width,
    height: bounds.height,
    windowWidth: slot.ownerDocument.documentElement.scrollWidth,
    windowHeight: slot.ownerDocument.documentElement.scrollHeight,
  });
};

const createStickerPdf = async (cards: string[], title: string) => {
  const frame = document.createElement('iframe');
  frame.setAttribute('aria-hidden', 'true');
  frame.style.position = 'fixed';
  frame.style.left = '-10000px';
  frame.style.top = '0';
  frame.style.width = '220mm';
  frame.style.height = '297mm';
  frame.style.border = '0';
  frame.style.opacity = '0';
  frame.style.pointerEvents = 'none';
  document.body.appendChild(frame);

  try {
    const frameDocument = frame.contentDocument;
    if (!frameDocument) throw new Error('Não foi possível preparar as etiquetas para o PDF.');

    frameDocument.open();
    frameDocument.write(buildStickerDocument(cards, title, false, false));
    frameDocument.close();

    await new Promise(resolve => window.setTimeout(resolve, 120));
    await waitForDocumentImages(frameDocument);
    if (frameDocument.fonts) await frameDocument.fonts.ready;

    const slots = Array.from(frameDocument.querySelectorAll<HTMLElement>('.sticker-slot'));
    if (!slots.length) throw new Error('Nenhuma etiqueta foi encontrada para gerar o PDF.');

    const renderedStickers: HTMLCanvasElement[] = [];
    for (const slot of slots) {
      renderedStickers.push(await renderStickerSlot(slot));
    }

    const mmToPixels = (millimeters: number) => Math.round((millimeters / 25.4) * PDF_DPI);
    const pageWidthPixels = mmToPixels(210);
    const pageHeightPixels = mmToPixels(297);
    const stickerPixels = mmToPixels(STICKER_DIAMETER_MM);
    const gapPixels = mmToPixels(STICKER_GAP_MM);
    const totalGridWidth = STICKERS_PER_ROW * stickerPixels + (STICKERS_PER_ROW - 1) * gapPixels;
    const totalGridHeight = STICKER_ROWS_PER_PAGE * stickerPixels + (STICKER_ROWS_PER_PAGE - 1) * gapPixels;
    const startX = Math.round((pageWidthPixels - totalGridWidth) / 2);
    const startY = Math.round((pageHeightPixels - totalGridHeight) / 2);
    const stickersPerPage = STICKERS_PER_ROW * STICKER_ROWS_PER_PAGE;
    const pdfPages: PdfJpegPage[] = [];

    for (let pageStart = 0; pageStart < renderedStickers.length; pageStart += stickersPerPage) {
      const pageCanvas = document.createElement('canvas');
      pageCanvas.width = pageWidthPixels;
      pageCanvas.height = pageHeightPixels;
      const pageContext = pageCanvas.getContext('2d');
      if (!pageContext) throw new Error('Canvas indisponível para montar a página do PDF.');
      pageContext.fillStyle = '#ffffff';
      pageContext.fillRect(0, 0, pageCanvas.width, pageCanvas.height);

      renderedStickers
        .slice(pageStart, pageStart + stickersPerPage)
        .forEach((sticker, localIndex) => {
          const column = localIndex % STICKERS_PER_ROW;
          const row = Math.floor(localIndex / STICKERS_PER_ROW);
          const x = startX + column * (stickerPixels + gapPixels);
          const y = startY + row * (stickerPixels + gapPixels);
          pageContext.drawImage(sticker, x, y, stickerPixels, stickerPixels);
        });

      const jpegDataUrl = pageCanvas.toDataURL('image/jpeg', 0.98);
      pdfPages.push({
        bytes: dataUrlToBytes(jpegDataUrl),
        width: pageCanvas.width,
        height: pageCanvas.height,
      });
    }

    return buildPdfBlob(pdfPages);
  } finally {
    frame.remove();
  }
};

export default function HydrometersPage() {
  const { notify } = useAppFeedback();
  const [items, setItems] = useState<Hydrometer[]>([]);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [editing, setEditing] = useState<Hydrometer | null>(null);
  const [saving, setSaving] = useState(false);
  const [statusUpdatingIds, setStatusUpdatingIds] = useState<Set<string>>(() => new Set());
  const [pdfBusy, setPdfBusy] = useState(false);
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
    installation_mode: 'dashboard_baseline' as 'dashboard_baseline' | 'field_capture',
    baseline_date: new Date().toISOString().slice(0, 10),
  });

  const load = () => {
    setLoading(true);
    api.get<{ items: Hydrometer[] }>('/hydrometers')
      .then(response => setItems(response.items))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  const loadCustomers = () => {
    api.get<{ items: Customer[] }>('/customers/options?status=active&limit=1000')
      .then(response => setCustomers(
        [...response.items].sort((left, right) =>
          Number(left.has_hydrometer) - Number(right.has_hydrometer)
          || left.name.localeCompare(right.name, 'pt-BR')
        )
      ))
      .catch(console.error);
  };

  useEffect(() => {
    load();
    loadCustomers();
  }, []);

  const handleAdd = async (event: FormEvent) => {
    event.preventDefault();
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
        installation_mode: form.installation_mode,
        baseline_date: form.installation_mode === 'dashboard_baseline' ? form.baseline_date : null,
      });
      setShowAdd(false);
      setForm({ customer_id: '', code: '', brand: '', model: '', red_digits: 3, black_digits: '', location_description: '', initial_reading: 0, installation_mode: 'dashboard_baseline', baseline_date: new Date().toISOString().slice(0, 10) });
      load();
      notify('Hidrômetro associado', 'O medidor foi vinculado com sucesso.', 'success');
    } catch (error: unknown) {
      notify('Falha ao associar hidrômetro', error instanceof Error ? error.message : 'Erro ao criar hidrômetro.', 'error');
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = async (event: FormEvent) => {
    event.preventDefault();
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
    } catch (error: unknown) {
      notify('Falha ao editar hidrômetro', error instanceof Error ? error.message : 'Erro ao salvar hidrômetro.', 'error');
    } finally {
      setSaving(false);
    }
  };

  const filteredItems = items.filter(hydrometer =>
    hydrometer.code.toLowerCase().includes(search.toLowerCase())
    || hydrometer.customer?.name.toLowerCase().includes(search.toLowerCase())
  );
  const activeCount = items.filter(hydrometer => hydrometer.is_active).length;
  const inactiveCount = items.length - activeCount;
  const countSubtitle = search.trim()
    ? `${filteredItems.length} encontrados de ${items.length} medidores · ${activeCount} ativos · ${inactiveCount} inativos`
    : `${items.length} medidores · ${activeCount} ativos · ${inactiveCount} inativos`;

  const createStickerCards = async (hydrometers: Hydrometer[]) => {
    const QRCode = await import('qrcode');
    return Promise.all(hydrometers.map(async hydrometer => {
      const qrValue = hydrometer.qr_code_token || hydrometer.code;
      const qrDataUrl = await QRCode.toDataURL(qrValue, {
        margin: 2,
        width: 720,
        errorCorrectionLevel: 'M',
      });
      return buildStickerMarkup(hydrometer, qrDataUrl);
    }));
  };

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

    printWindow.document.write(`<html><head><title>${COMPANY_NAME}</title></head><body><p>Gerando etiquetas...</p></body></html>`);
    try {
      const cards = await createStickerCards(hydrometers);
      printWindow.document.open();
      printWindow.document.write(buildStickerDocument(cards, title, singleSticker));
      printWindow.document.close();
    } catch (error: unknown) {
      printWindow.close();
      notify('Falha ao gerar etiquetas', error instanceof Error ? error.message : 'Não foi possível montar as etiquetas dos hidrômetros.', 'error');
    }
  };

  const downloadStickerPdf = async (hydrometers: Hydrometer[], fileName: string) => {
    setPdfBusy(true);
    try {
      const cards = await createStickerCards(hydrometers);
      const pdfBlob = await createStickerPdf(cards, `${COMPANY_NAME} - Etiquetas de hidrômetros`);
      const objectUrl = URL.createObjectURL(pdfBlob);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = fileName;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
      notify('PDF gerado', 'O arquivo das etiquetas foi baixado com sucesso.', 'success');
    } catch (error: unknown) {
      notify('Falha ao baixar PDF', error instanceof Error ? error.message : 'Não foi possível gerar o PDF das etiquetas.', 'error');
    } finally {
      setPdfBusy(false);
    }
  };

  const printQrSticker = async (hydrometer: Hydrometer) => {
    const customerName = hydrometer.customer?.name || hydrometer.code;
    await openStickerPrintWindow([hydrometer], `Etiqueta - ${customerName}`, true);
  };

  const downloadQrStickerPdf = async (hydrometer: Hydrometer) => {
    const customerName = hydrometer.customer?.name || hydrometer.code;
    await downloadStickerPdf([hydrometer], `etiqueta-${sanitizeFileName(customerName)}.pdf`);
  };

  const selectedHydrometers = search.trim() ? filteredItems : items;

  const printAllStickers = async () => {
    if (!selectedHydrometers.length) {
      notify('Nenhuma etiqueta para imprimir', 'Cadastre um hidrômetro ou ajuste a busca antes de imprimir.', 'warning');
      return;
    }
    await openStickerPrintWindow(selectedHydrometers, `${COMPANY_NAME} - Etiquetas de hidrômetros`);
  };

  const downloadAllStickersPdf = async () => {
    if (!selectedHydrometers.length) {
      notify('Nenhuma etiqueta para baixar', 'Cadastre um hidrômetro ou ajuste a busca antes de gerar o PDF.', 'warning');
      return;
    }
    await downloadStickerPdf(selectedHydrometers, 'etiquetas-mar-azul-servicos.pdf');
  };

  const disconnectHydrometer = async (hydrometer: Hydrometer) => {
    if (statusUpdatingIds.has(hydrometer.id)) return;
    setItems(current => current.map(item => (
      item.id === hydrometer.id
        ? { ...item, is_active: false, disconnected_at: new Date().toISOString() }
        : item
    )));
    setStatusUpdatingIds(current => new Set(current).add(hydrometer.id));
    try {
      const updated = await api.post<Hydrometer>(`/hydrometers/${hydrometer.id}/disconnect`, { reason: 'Falta de pagamento' });
      setItems(current => current.map(item => item.id === updated.id ? updated : item));
      notify('Hidrômetro desligado', 'O cliente foi marcado como desligado.', 'warning');
    } catch (error: unknown) {
      setItems(current => current.map(item => item.id === hydrometer.id ? hydrometer : item));
      notify('Falha ao desligar', error instanceof Error ? error.message : 'Erro ao desligar hidrômetro.', 'error');
    } finally {
      setStatusUpdatingIds(current => {
        const next = new Set(current);
        next.delete(hydrometer.id);
        return next;
      });
    }
  };

  const [reconnecting, setReconnecting] = useState<Hydrometer | null>(null);

  const reconnectHydrometer = async (hydrometer: Hydrometer, mode: ReconnectMode) => {
    if (statusUpdatingIds.has(hydrometer.id)) return;
    setReconnecting(null);
    setItems(current => current.map(item => (
      item.id === hydrometer.id
        ? { ...item, is_active: true, reconnected_at: new Date().toISOString() }
        : item
    )));
    setStatusUpdatingIds(current => new Set(current).add(hydrometer.id));
    try {
      const updated = await api.post<Hydrometer>(`/hydrometers/${hydrometer.id}/reconnect`, { mode });
      setItems(current => current.map(item => item.id === updated.id ? updated : item));
      notify(
        'Religamento registrado',
        mode === 'with_fee'
          ? 'O hidrômetro voltou para leitura e a taxa de religamento foi gerada.'
          : 'O hidrômetro voltou para leitura sem gerar taxa de religamento.',
        'success',
      );
    } catch (error: unknown) {
      setItems(current => current.map(item => item.id === hydrometer.id ? hydrometer : item));
      notify('Falha ao religar', error instanceof Error ? error.message : 'Erro ao religar hidrômetro.', 'error');
    } finally {
      setStatusUpdatingIds(current => {
        const next = new Set(current);
        next.delete(hydrometer.id);
        return next;
      });
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
            onChange={event => setSearch(event.target.value)}
          />
        </div>
        <button className="btn btn-primary" onClick={() => setShowAdd(true)}>
          <Plus size={16} /> Associar Novo Hidrômetro
        </button>
        <button className="btn btn-secondary" onClick={printAllStickers} disabled={loading || !items.length}>
          <Printer size={16} /> Imprimir etiquetas
        </button>
        <button className="btn btn-secondary" onClick={downloadAllStickersPdf} disabled={loading || !items.length || pdfBusy}>
          {pdfBusy ? <Loader2 size={16} className="spinner" /> : <FileDown size={16} />}
          {pdfBusy ? 'Gerando PDF...' : 'Baixar PDF'}
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
              [...Array(5)].map((_, index) => (
                <tr key={index}>
                  <td><div className="skeleton" style={{ height: 20, width: '90%' }} /></td>
                  <td><div className="skeleton" style={{ height: 20, width: '60%' }} /></td>
                  <td><div className="skeleton" style={{ height: 20, width: '70%' }} /></td>
                  <td><div className="skeleton" style={{ height: 20, width: '40%' }} /></td>
                  <td><div className="skeleton" style={{ height: 24, width: 60, borderRadius: 99 }} /></td>
                </tr>
              ))
            ) : !filteredItems.length ? (
              <tr><td colSpan={7}><div className="empty-state"><Droplets /><p>Nenhum hidrômetro encontrado</p></div></td></tr>
            ) : filteredItems.map(hydrometer => (
              <tr key={hydrometer.id}>
                <td>
                  <div className="cell-primary" style={{ fontWeight: 800 }}>QR {hydrometer.code}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{hydrometer.customer?.name || 'Cliente desconhecido'}</div>
                </td>
                <td>{[hydrometer.brand, hydrometer.model].filter(Boolean).join(' ') || '—'}</td>
                <td>{hydrometer.red_digits || 3} vermelhos{hydrometer.black_digits ? ` · ${hydrometer.black_digits} pretos` : ''}</td>
                <td>{hydrometer.location_description || '—'}</td>
                <td>
                  <span style={{ fontWeight: 600 }}>{hydrometer.last_reading_value.toFixed(2)} m³</span>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {hydrometer.last_reading_date ? new Date(hydrometer.last_reading_date).toLocaleDateString('pt-BR') : 'Sem leituras'}
                  </div>
                </td>
                <td><span className={`badge ${hydrometer.is_active ? 'active' : 'suspended'}`}>{hydrometer.is_active ? 'Ativo' : 'Inativo'}</span></td>
                <td>
                  <div style={{ display: 'flex', gap: 6 }}>
                    <button className="btn btn-ghost btn-icon btn-sm" onClick={() => printQrSticker(hydrometer)} title="Imprimir etiqueta do hidrômetro">
                      <Printer size={14} />
                    </button>
                    <button className="btn btn-ghost btn-icon btn-sm" onClick={() => downloadQrStickerPdf(hydrometer)} title="Baixar etiqueta em PDF" disabled={pdfBusy}>
                      <FileDown size={14} />
                    </button>
                    {hydrometer.is_active ? (
                      <button className="btn btn-ghost btn-icon btn-sm" onClick={() => disconnectHydrometer(hydrometer)} title="Desligar hidrômetro" disabled={statusUpdatingIds.has(hydrometer.id)}>
                        {statusUpdatingIds.has(hydrometer.id) ? <Loader2 size={14} className="spinner" /> : <Power size={14} />}
                      </button>
                    ) : (
                      <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setReconnecting(hydrometer)} title="Religar hidrômetro" disabled={statusUpdatingIds.has(hydrometer.id)}>
                        {statusUpdatingIds.has(hydrometer.id) ? <Loader2 size={14} className="spinner" /> : <RotateCcw size={14} />}
                      </button>
                    )}
                    <button className="btn btn-ghost btn-icon btn-sm" onClick={() => setEditing(hydrometer)} title="Editar hidrômetro">
                      <Pencil size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {reconnecting && (
        <div className="modal-overlay">
          <div className="modal" role="dialog" aria-modal="true" aria-labelledby="reconnect-title">
            <div className="modal-header">
              <div>
                <h2 className="modal-title" id="reconnect-title">Como deseja religar?</h2>
                <p style={{ margin: '6px 0 0', color: 'var(--text-muted)', fontSize: 13 }}>
                  {reconnecting.customer?.name || 'Cliente'} · hidrômetro {reconnecting.code}
                </p>
              </div>
              <button className="btn btn-ghost btn-icon" onClick={() => setReconnecting(null)} aria-label="Fechar"><X size={20} /></button>
            </div>
            <div style={{ display: 'grid', gap: 12 }}>
              <button className="btn btn-ghost" style={{ height: 'auto', padding: 16, textAlign: 'left', justifyContent: 'flex-start' }} onClick={() => reconnectHydrometer(reconnecting, 'reading_only')}>
                <span><strong>Voltar apenas para leitura</strong><br /><small style={{ color: 'var(--text-muted)' }}>Reativa cliente e hidrômetro sem criar cobrança.</small></span>
              </button>
              <button className="btn btn-primary" style={{ height: 'auto', padding: 16, textAlign: 'left', justifyContent: 'flex-start' }} onClick={() => reconnectHydrometer(reconnecting, 'with_fee')}>
                <span><strong>Religar com taxa</strong><br /><small>Reativa e emite a taxa de religamento configurada.</small></span>
              </button>
            </div>
            <div className="modal-footer">
              <button type="button" className="btn btn-ghost" onClick={() => setReconnecting(null)}>Cancelar</button>
            </div>
          </div>
        </div>
      )}

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
                  onChange={event => setForm({ ...form, customer_id: event.target.value })}
                  required
                >
                  <option value="">Selecione um cliente...</option>
                  {customers.map(customer => (
                    <option key={customer.id} value={customer.id}>
                      {customer.name} ({customer.has_hydrometer ? 'já possui hidrômetro' : 'sem hidrômetro'}) — {customer.cpf_cnpj}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Código do Hidrômetro (números)</label>
                <input
                  className="form-input"
                  placeholder="Ex: 000123 (deixe em branco para gerar)"
                  value={form.code}
                  onChange={event => setForm({ ...form, code: event.target.value.replace(/\D/g, '') })}
                  inputMode="numeric"
                  maxLength={12}
                />
              </div>

              <div className="form-grid" style={{ marginBottom: 16 }}>
                <div className="form-group">
                  <label className="form-label">Marca (Opcional)</label>
                  <input className="form-input" value={form.brand} onChange={event => setForm({ ...form, brand: event.target.value })} />
                </div>
                <div className="form-group">
                  <label className="form-label">Modelo (Opcional)</label>
                  <input className="form-input" value={form.model} onChange={event => setForm({ ...form, model: event.target.value })} />
                </div>
              </div>

              <div className="form-grid" style={{ marginBottom: 16 }}>
                <div className="form-group">
                  <label className="form-label">Dígitos vermelhos</label>
                  <select className="form-select" value={form.red_digits} onChange={event => setForm({ ...form, red_digits: Number(event.target.value) })}>
                    <option value={2}>2 dígitos vermelhos</option>
                    <option value={3}>3 dígitos vermelhos</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Dígitos pretos</label>
                  <input className="form-input" type="number" min={1} value={form.black_digits} onChange={event => setForm({ ...form, black_digits: event.target.value })} placeholder="Opcional" />
                </div>
              </div>

              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Localização no Imóvel (Opcional)</label>
                <input className="form-input" placeholder="Ex: Muro frontal esquerdo" value={form.location_description} onChange={event => setForm({ ...form, location_description: event.target.value })} />
              </div>

              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Forma de instalação</label>
                <select
                  className="form-select"
                  value={form.installation_mode}
                  onChange={event => setForm({ ...form, installation_mode: event.target.value as 'dashboard_baseline' | 'field_capture' })}
                >
                  <option value="dashboard_baseline">Registrar leitura-base agora pelo dashboard</option>
                  <option value="field_capture">Aguardar foto e instalação pelo app</option>
                </select>
              </div>

              {form.installation_mode === 'dashboard_baseline' && (
                <div className="form-grid" style={{ marginBottom: 16 }}>
                  <div className="form-group">
                    <label className="form-label">Última leitura-base (m³)</label>
                    <input className="form-input" type="number" step="0.001" min="0" value={form.initial_reading} onChange={event => setForm({ ...form, initial_reading: Number(event.target.value) })} required />
                  </div>
                  <div className="form-group">
                    <label className="form-label">Data da leitura-base</label>
                    <input className="form-input" type="date" value={form.baseline_date} max={new Date().toISOString().slice(0, 10)} onChange={event => setForm({ ...form, baseline_date: event.target.value })} required />
                  </div>
                </div>
              )}

              <div style={{ marginBottom: 24, padding: 12, borderRadius: 8, background: 'var(--bg-tertiary)', color: 'var(--text-secondary)', fontSize: 12, lineHeight: 1.5 }}>
                {form.installation_mode === 'dashboard_baseline'
                  ? 'A leitura será oficializada sem consumo e sem taxa de instalação. O próximo ciclo será uma leitura normal; não será necessária captura de instalação no app.'
                  : 'O hidrômetro aparecerá como instalação pendente no app e a leitura-base só será oficial após a foto e a aprovação do gestor.'}
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
                  <input className="form-input" value={editing.code} onChange={event => setEditing({ ...editing, code: event.target.value.replace(/\D/g, '') })} inputMode="numeric" />
                </div>
                <div className="form-group">
                  <label className="form-label">Última leitura base</label>
                  <input className="form-input" type="number" step="0.001" min="0" value={editing.last_reading_value} onChange={event => setEditing({ ...editing, last_reading_value: parseFloat(event.target.value) || 0 })} />
                </div>
              </div>
              <div className="form-grid" style={{ marginBottom: 16 }}>
                <div className="form-group">
                  <label className="form-label">Marca</label>
                  <input className="form-input" value={editing.brand || ''} onChange={event => setEditing({ ...editing, brand: event.target.value })} />
                </div>
                <div className="form-group">
                  <label className="form-label">Modelo</label>
                  <input className="form-input" value={editing.model || ''} onChange={event => setEditing({ ...editing, model: event.target.value })} />
                </div>
              </div>
              <div className="form-grid" style={{ marginBottom: 16 }}>
                <div className="form-group">
                  <label className="form-label">Dígitos vermelhos</label>
                  <select className="form-select" value={editing.red_digits || 3} onChange={event => setEditing({ ...editing, red_digits: Number(event.target.value) })}>
                    <option value={2}>2 dígitos vermelhos</option>
                    <option value={3}>3 dígitos vermelhos</option>
                  </select>
                </div>
                <div className="form-group">
                  <label className="form-label">Dígitos pretos</label>
                  <input className="form-input" type="number" min={1} value={editing.black_digits || ''} onChange={event => setEditing({ ...editing, black_digits: event.target.value ? Number(event.target.value) : null })} placeholder="Opcional" />
                </div>
              </div>
              <div className="form-group" style={{ marginBottom: 16 }}>
                <label className="form-label">Localização</label>
                <input className="form-input" value={editing.location_description || ''} onChange={event => setEditing({ ...editing, location_description: event.target.value })} />
              </div>
              <div className="form-group" style={{ marginBottom: 24 }}>
                <label className="form-label">Status</label>
                <select className="form-select" value={editing.is_active ? 'true' : 'false'} onChange={event => setEditing({ ...editing, is_active: event.target.value === 'true' })}>
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
