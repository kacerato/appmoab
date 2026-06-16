'use client';

import { useEffect, useMemo, useState } from 'react';
import Header from '@/components/Header';
import { api } from '@/lib/api';
import { BrainCircuit, CheckCircle2, Loader2, MessageCircle, Send, ToggleLeft, Zap } from 'lucide-react';

interface HealthData {
  status: string;
  whatsapp_enabled: boolean;
}

interface OcrMemorySummary {
  total: number;
  correct: number;
  wrong: number;
  accuracy: number;
  recent: Array<{
    id: string;
    stage: string;
    predicted_code: string | null;
    confirmed_code: string | null;
    predicted_value: number | null;
    confirmed_value: number | null;
    red_digits: number | null;
    black_digits: number | null;
    hydrometer_brand: string | null;
    hydrometer_model: string | null;
    was_correct: boolean | null;
    lesson: string | null;
    reasoning_log: string | null;
    divergence_reason: string | null;
  }>;
}

const FLOW_DEFINITIONS = [
  {
    key: 'invoice_generated',
    title: 'Fatura gerada',
    description: 'Permite enviar a cobrança pela tela da fatura.',
  },
  {
    key: 'reminder_before_due',
    title: 'Lembrete antes do vencimento',
    description: 'Avisa o cliente alguns dias antes da data de pagamento.',
    hasDays: true,
  },
  {
    key: 'due_today',
    title: 'Vence hoje',
    description: 'Avisa o cliente no próprio dia do vencimento.',
  },
  {
    key: 'overdue',
    title: 'Fatura atrasada',
    description: 'Envia aviso quando existir cobrança em atraso.',
    hasDays: true,
  },
  {
    key: 'payment_confirmed',
    title: 'Pagamento confirmado',
    description: 'Confirma para o cliente quando o pagamento for registrado.',
  },
];

interface NotificationFlowSetting {
  enabled: boolean;
  days?: number;
  message?: string;
}

interface SystemSetting {
  route_window_enabled: boolean;
  route_window_days_before_due: number;
  route_window_days_after_due: number;
  daily_interest_percent: number;
  late_fee_percent: number;
  installation_fee_amount: number;
  reconnection_fee_amount: number;
  cut_notice_days_after_due: number;
  default_due_day: number;
  auto_send_invoice_on_approval: boolean;
  notification_flows: Record<string, NotificationFlowSetting>;
}

const DEFAULT_NOTIFICATION_FLOWS: Record<string, NotificationFlowSetting> = {
  invoice_generated: { enabled: true, message: 'Olá, sua fatura foi gerada. Consulte o valor e o vencimento no atendimento.' },
  reminder_before_due: { enabled: true, days: 5, message: 'Olá, sua fatura vence em breve. Evite atraso fazendo o pagamento até o vencimento.' },
  due_today: { enabled: true, message: 'Olá, sua fatura vence hoje. Se já pagou, desconsidere esta mensagem.' },
  overdue: { enabled: true, days: 1, message: 'Olá, identificamos uma fatura em atraso. Regularize para evitar bloqueios.' },
  payment_confirmed: { enabled: true, message: 'Pagamento confirmado. Obrigado!' },
};

export default function NotificationsPage() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [ocrMemory, setOcrMemory] = useState<OcrMemorySummary | null>(null);
  const [showOcrMemory, setShowOcrMemory] = useState(false);
  const [loading, setLoading] = useState(true);
  const [settings, setSettings] = useState<SystemSetting | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get<HealthData>('/health')
      .then(setHealth)
      .catch(console.error)
      .finally(() => setLoading(false));
    api.get<OcrMemorySummary>('/hydrometers/ocr-memory/summary')
      .then(setOcrMemory)
      .catch(console.error);
    api.get<SystemSetting>('/system-settings')
      .then(data => setSettings({
        ...data,
        auto_send_invoice_on_approval: data.auto_send_invoice_on_approval ?? false,
        notification_flows: {
          ...DEFAULT_NOTIFICATION_FLOWS,
          ...(data.notification_flows || {}),
        },
      }))
      .catch(console.error);
  }, []);

  const statusTone = useMemo(() => {
    if (!health?.whatsapp_enabled) {
      return {
        label: 'Pronto para ativação',
        color: 'var(--warning)',
        description: 'Você pode deixar os avisos configurados. Eles só serão enviados quando o número estiver conectado.',
      };
    }

    return {
      label: 'Canal ativo',
      color: 'var(--success)',
      description: 'O número está conectado e pronto para enviar cobranças e avisos.',
    };
  }, [health?.whatsapp_enabled]);

  const updateFlow = (key: string, patch: Partial<NotificationFlowSetting>) => {
    setSettings(current => current ? ({
      ...current,
      notification_flows: {
        ...current.notification_flows,
        [key]: {
          ...DEFAULT_NOTIFICATION_FLOWS[key],
          ...(current.notification_flows[key] || {}),
          ...patch,
        },
      },
    }) : current);
  };

  const saveSettings = async () => {
    if (!settings) return;
    setSaving(true);
    try {
      const updated = await api.patch<SystemSetting>('/system-settings', settings);
      setSettings({
        ...updated,
        notification_flows: {
          ...DEFAULT_NOTIFICATION_FLOWS,
          ...(updated.notification_flows || {}),
        },
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <>
      <Header title="Notificações" subtitle="Central de fluxos e comunicação" />

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-header">
          <span className="card-title">Status do WhatsApp</span>
        </div>

        {loading ? (
          <div className="loading-page" style={{ minHeight: 120 }}>
            <Loader2 size={18} className="spinner" />
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, padding: '8px 0' }}>
            <div className={`kpi-icon ${health?.whatsapp_enabled ? 'blue' : 'orange'}`} style={{ width: 40, height: 40 }}>
              <MessageCircle size={18} />
            </div>
            <div>
              <div style={{ fontWeight: 600, color: statusTone.color }}>{statusTone.label}</div>
              <div style={{ fontSize: 12, color: 'var(--text-muted)', maxWidth: 620 }}>
                {statusTone.description}
              </div>
            </div>
          </div>
        )}
      </div>

      <button
        className="card"
        type="button"
        onClick={() => setShowOcrMemory(current => !current)}
        style={{
          marginBottom: 20,
          width: '100%',
          textAlign: 'left',
          cursor: 'pointer',
          borderColor: showOcrMemory ? 'var(--accent)' : undefined,
        }}
      >
        <div className="card-header">
          <span className="card-title">GLM-OCR</span>
          <span className="badge active">{ocrMemory ? `${ocrMemory.accuracy}% acerto` : 'Carregando'}</span>
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          OCR de hidrômetros e validação de consumo
        </div>
      </button>

      {showOcrMemory && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-header">
            <span className="card-title">Memória de aprendizado operacional</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(180px, 1fr) minmax(180px, 1fr) minmax(180px, 1fr)', gap: 12, marginBottom: 16 }}>
            <MemoryStat icon={<BrainCircuit size={18} />} label="Amostras" value={ocrMemory?.total ?? 0} tone="blue" />
            <MemoryStat icon={<CheckCircle2 size={18} />} label="Acertos" value={ocrMemory?.correct ?? 0} tone="green" />
            <MemoryStat icon={<Zap size={18} />} label="Divergências" value={ocrMemory?.wrong ?? 0} tone="orange" />
          </div>
          <div style={{ display: 'grid', gap: 10 }}>
            {(ocrMemory?.recent || []).map(item => (
              <div key={item.id} style={{ padding: 14, borderRadius: 'var(--radius-md)', border: '1px solid var(--border)', background: 'var(--bg-card)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'center' }}>
                  <div>
                    <strong style={{ fontSize: 13 }}>{item.stage === 'code' ? 'Código do hidrômetro' : 'Leitura do visor'}</strong>
                    <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>
                      {item.red_digits || 'n/i'} vermelhos{item.black_digits ? ` · ${item.black_digits} pretos` : ''}{item.hydrometer_brand ? ` · ${[item.hydrometer_brand, item.hydrometer_model].filter(Boolean).join(' ')}` : ''}
                    </div>
                  </div>
                  <span className={`badge ${item.was_correct ? 'active' : item.was_correct === false ? 'rejected' : 'pending'}`}>
                    {item.was_correct ? 'Acertou' : item.was_correct === false ? 'Revisar' : 'Pendente'}
                  </span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, marginTop: 10 }}>
                  <Readout label="GLM-OCR" value={item.predicted_code || item.predicted_value || 'sem leitura'} />
                  <Readout label="Humano" value={item.confirmed_code || item.confirmed_value || 'sem confirmação'} />
                </div>
                {item.lesson && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 10 }}>{item.lesson}</div>}
                {item.divergence_reason && <div style={{ fontSize: 12, color: 'var(--danger)', marginTop: 8 }}>Possível causa: {item.divergence_reason}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-header">
          <span className="card-title">Automação de faturas</span>
          <button
            className={`btn btn-sm ${settings?.auto_send_invoice_on_approval ? 'btn-primary' : 'btn-secondary'}`}
            type="button"
            onClick={() => setSettings(current => current ? ({ ...current, auto_send_invoice_on_approval: !current.auto_send_invoice_on_approval }) : current)}
            disabled={!settings}
          >
            {settings?.auto_send_invoice_on_approval ? 'Ligado' : 'Desligado'}
          </button>
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-muted)', maxWidth: 720 }}>
          Quando ligado, a aprovação da leitura gera a cobrança Efí e envia automaticamente o link da fatura por WhatsApp, sem esperar o dia do vencimento.
        </div>
      </div>

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-header">
          <span className="card-title">Como vai funcionar</span>
        </div>
        <div style={{ display: 'grid', gap: 12 }}>
          <FlowInfo
            icon={<CheckCircle2 size={16} />}
            title="Enviar pela fatura"
            text="Abra uma fatura e envie a cobrança para o telefone cadastrado do cliente."
          />
          <FlowInfo
            icon={<ToggleLeft size={16} />}
            title="Escolher avisos automáticos"
            text="Ligue apenas os avisos que deseja usar e ajuste os dias de lembrete."
          />
          <FlowInfo
            icon={<Send size={16} />}
            title="Mensagens do seu jeito"
            text="Revise o texto de cada aviso antes de salvar."
          />
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Fluxos disponíveis</span>
          <button className="btn btn-primary btn-sm" type="button" onClick={saveSettings} disabled={saving || !settings}>
            {saving ? <Loader2 size={14} className="spinner" /> : null} Salvar fluxos
          </button>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {FLOW_DEFINITIONS.map(flow => (
            <div
              key={flow.key}
              style={{
                padding: 14,
                background: 'var(--navy-900)',
                borderRadius: 'var(--radius-md)',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                gap: 12,
              }}
            >
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{flow.title}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{flow.description}</div>
                {flow.hasDays && (
                  <div className="form-group" style={{ marginTop: 10, maxWidth: 220 }}>
                    <label className="form-label">Dias</label>
                    <input
                      className="form-input"
                      type="number"
                      min={1}
                      max={30}
                      value={settings?.notification_flows[flow.key]?.days ?? DEFAULT_NOTIFICATION_FLOWS[flow.key].days ?? 1}
                      onChange={e => updateFlow(flow.key, { days: parseInt(e.target.value, 10) || 1 })}
                    />
                  </div>
                )}
                <textarea
                  className="form-input"
                  rows={2}
                  style={{ marginTop: 10, resize: 'vertical' }}
                  value={settings?.notification_flows[flow.key]?.message ?? DEFAULT_NOTIFICATION_FLOWS[flow.key].message ?? ''}
                  onChange={e => updateFlow(flow.key, { message: e.target.value })}
                />
              </div>
              <button
                className={`btn btn-sm ${settings?.notification_flows[flow.key]?.enabled ?? true ? 'btn-primary' : 'btn-secondary'}`}
                type="button"
                onClick={() => updateFlow(flow.key, { enabled: !(settings?.notification_flows[flow.key]?.enabled ?? true) })}
              >
                {settings?.notification_flows[flow.key]?.enabled ?? true ? 'Ligado' : 'Desligado'}
              </button>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

function MemoryStat({ icon, label, value, tone }: { icon: React.ReactNode; label: string; value: number; tone: 'blue' | 'green' | 'orange' }) {
  const color = tone === 'green' ? 'var(--success)' : tone === 'orange' ? 'var(--warning)' : 'var(--accent)';
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius-md)', padding: 14, display: 'flex', alignItems: 'center', gap: 12 }}>
      <div className={`kpi-icon ${tone === 'orange' ? 'orange' : 'blue'}`} style={{ width: 38, height: 38, color }}>{icon}</div>
      <div>
        <div style={{ fontSize: 22, fontWeight: 800 }}>{value}</div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{label}</div>
      </div>
    </div>
  );
}

function Readout({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ padding: 10, borderRadius: 'var(--radius-sm)', background: 'var(--blue-50)' }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 800 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 700, marginTop: 2 }}>{value}</div>
    </div>
  );
}

function FlowInfo({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return (
    <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
      <div className="kpi-icon blue" style={{ width: 34, height: 34, flexShrink: 0 }}>
        {icon}
      </div>
      <div>
        <div style={{ fontWeight: 600, fontSize: 13 }}>{title}</div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{text}</div>
      </div>
    </div>
  );
}
