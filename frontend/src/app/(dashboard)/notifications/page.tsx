'use client';

import { useEffect, useMemo, useState } from 'react';
import Header from '@/components/Header';
import { api } from '@/lib/api';
import { CheckCircle2, Loader2, MessageCircle, Settings2, TriangleAlert } from 'lucide-react';

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
  }>;
}

const FLOW_DEFINITIONS = [
  {
    key: 'invoice_generated',
    title: 'Fatura gerada',
    description: 'Disparo manual pela tela de faturas, usando o telefone do cliente cadastrado.',
    mode: 'manual',
  },
  {
    key: 'reminder_5d',
    title: 'Lembrete 5 dias antes',
    description: 'Estrutura de envio automático já existe no backend e depende apenas do canal ativo.',
    mode: 'automatic',
  },
  {
    key: 'due_today',
    title: 'Vence hoje',
    description: 'Fluxo preparado para comunicação no dia do vencimento.',
    mode: 'automatic',
  },
  {
    key: 'overdue_1d',
    title: 'Fatura atrasada',
    description: 'Fluxo preparado para cobrança após o vencimento.',
    mode: 'automatic',
  },
  {
    key: 'payment_confirmed',
    title: 'Pagamento confirmado',
    description: 'Template previsto para confirmação de pagamento.',
    mode: 'automatic',
  },
];

export default function NotificationsPage() {
  const [health, setHealth] = useState<HealthData | null>(null);
  const [kimiMemory, setKimiMemory] = useState<KimiMemorySummary | null>(null);
  const [showKimiMemory, setShowKimiMemory] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get<HealthData>('/health')
      .then(setHealth)
      .catch(console.error)
      .finally(() => setLoading(false));
    api.get<KimiMemorySummary>('/hydrometers/kimi-memory/summary')
      .then(setKimiMemory)
      .catch(console.error);
  }, []);

  const statusTone = useMemo(() => {
    if (!health?.whatsapp_enabled) {
      return {
        label: 'Pronto para ativação',
        color: 'var(--warning)',
        description: 'O painel já pode ser configurado antes do número ser conectado. Quando a instância do WhatsApp estiver ativa, os fluxos passam a usar o canal automaticamente.',
      };
    }

    return {
      label: 'Canal ativo',
      color: 'var(--success)',
      description: 'A central está pronta para usar o WhatsApp conectado no backend.',
    };
  }, [health?.whatsapp_enabled]);

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
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-header">
          <span className="card-title">Como o fluxo funciona hoje</span>
        </div>
        <div style={{ display: 'grid', gap: 12 }}>
          <FlowInfo
            icon={<CheckCircle2 size={16} />}
            title="Cobrança manual já pronta"
            text="Na lista e no detalhe de faturas, o sistema já usa o telefone do cadastro e informa claramente por que não conseguiu enviar, se houver falha."
          />
          <FlowInfo
            icon={<Settings2 size={16} />}
            title="Automação preparada no backend"
            text="Os lembretes automáticos já têm estrutura no backend. O que faltava aqui era a tela refletir isso corretamente, sem depender de .env local ou Meta Business."
          />
          <FlowInfo
            icon={<TriangleAlert size={16} />}
            title="Ativação do número não bloqueia a configuração"
            text="Você pode revisar o fluxo agora. O canal só entra em ação quando o WhatsApp estiver conectado, mas a lógica de cobrança e os gatilhos já podem ficar alinhados antes disso."
          />
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Fluxos disponíveis</span>
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
                alignItems: 'center',
                gap: 12,
              }}
            >
              <div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{flow.title}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{flow.description}</div>
              </div>
              <span className={`badge ${flow.mode === 'automatic' ? 'active' : 'pending'}`}>
                {flow.mode === 'automatic' ? 'Automático' : 'Manual'}
              </span>
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
