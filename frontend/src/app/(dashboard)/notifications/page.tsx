'use client';

import { useEffect, useMemo, useState } from 'react';
import Header from '@/components/Header';
import { api } from '@/lib/api';
import { CheckCircle2, Loader2, MessageCircle, Send, ToggleLeft } from 'lucide-react';

interface HealthData {
  status: string;
  whatsapp_enabled: boolean;
}

interface KimiMemorySummary {
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
  const [kimiMemory, setKimiMemory] = useState<KimiMemorySummary | null>(null);
  const [showKimiMemory, setShowKimiMemory] = useState(false);
  const [loading, setLoading] = useState(true);
  const [settings, setSettings] = useState<SystemSetting | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.get<HealthData>('/health')
      .then(setHealth)
      .catch(console.error)
      .finally(() => setLoading(false));
    api.get<KimiMemorySummary>('/hydrometers/kimi-memory/summary')
      .then(setKimiMemory)
      .catch(console.error);
    api.get<SystemSetting>('/system-settings')
      .then(data => setSettings({
        ...data,
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
        onClick={() => setShowKimiMemory(current => !current)}
        style={{
          marginBottom: 20,
          width: '100%',
          textAlign: 'left',
          cursor: 'pointer',
          borderColor: showKimiMemory ? 'var(--accent)' : undefined,
        }}
      >
        <div className="card-header">
          <span className="card-title">Kimi K2.6 Vision</span>
          <span className="badge active">{kimiMemory ? `${kimiMemory.accuracy}% acerto` : 'Carregando'}</span>
        </div>
        <div style={{ fontSize: 13, color: 'var(--text-muted)' }}>
          OCR de hidrômetros e validação de consumo
        </div>
      </button>

      {showKimiMemory && (
        <div className="card" style={{ marginBottom: 20 }}>
          <div className="card-header">
            <span className="card-title">Memória de aprendizado operacional</span>
          </div>
          <div className="kpi-grid" style={{ marginBottom: 16 }}>
            <MiniStat label="Amostras" value={kimiMemory?.total ?? 0} />
            <MiniStat label="Acertos" value={kimiMemory?.correct ?? 0} />
            <MiniStat label="Divergências" value={kimiMemory?.wrong ?? 0} />
          </div>
          <div style={{ display: 'grid', gap: 10 }}>
            {(kimiMemory?.recent || []).map(item => (
              <div key={item.id} style={{ padding: 12, borderRadius: 'var(--radius-md)', background: 'var(--navy-900)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
                  <strong style={{ fontSize: 13 }}>{item.stage === 'code' ? 'Código' : 'Leitura'}</strong>
                  <span className={`badge ${item.was_correct ? 'active' : item.was_correct === false ? 'rejected' : 'pending'}`}>
                    {item.was_correct ? 'Acertou' : item.was_correct === false ? 'Revisar' : 'Pendente'}
                  </span>
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>
                  Kimi: {item.predicted_code || item.predicted_value || 'sem leitura'} · Humano: {item.confirmed_code || item.confirmed_value || 'sem confirmacao'}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>
                  Formato: {item.red_digits || 'n/i'} vermelhos{item.black_digits ? ` · ${item.black_digits} pretos` : ''}{item.hydrometer_brand ? ` · ${[item.hydrometer_brand, item.hydrometer_model].filter(Boolean).join(' ')}` : ''}
                </div>
                {item.lesson && <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6 }}>{item.lesson}</div>}
                {item.reasoning_log && <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 6 }}>Log: {item.reasoning_log}</div>}
                {item.divergence_reason && <div style={{ fontSize: 12, color: 'var(--danger)', marginTop: 6 }}>Possivel causa: {item.divergence_reason}</div>}
              </div>
            ))}
          </div>
        </div>
      )}

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

function MiniStat({ label, value }: { label: string; value: number }) {
  return (
    <div className="kpi-card">
      <div className="kpi-value">{value}</div>
      <div className="kpi-sub">{label}</div>
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
