'use client';

import Header from '@/components/Header';
import { Bell, MessageCircle, Info } from 'lucide-react';

export default function NotificationsPage() {
  return (
    <>
      <Header title="Notificações" subtitle="Central de comunicações" />

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="card-header">
          <span className="card-title">Status do WhatsApp</span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 0' }}>
          <div className="kpi-icon orange" style={{ width: 40, height: 40 }}><MessageCircle size={18} /></div>
          <div>
            <div style={{ fontWeight: 600, color: 'var(--warning)' }}>Desativado</div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              Configure WHATSAPP_ENABLED=true no .env quando tiver um número cadastrado no Meta Business
            </div>
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-header">
          <span className="card-title">Templates Preparados</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {[
            { name: 'fatura_vencimento_proximo', desc: 'Enviado 5 dias antes do vencimento', type: 'reminder_5d' },
            { name: 'fatura_vence_hoje', desc: 'Enviado no dia do vencimento', type: 'due_today' },
            { name: 'fatura_atrasada', desc: 'Enviado 1 dia após vencimento', type: 'overdue_1d' },
            { name: 'pagamento_confirmado', desc: 'Enviado ao confirmar pagamento', type: 'payment_confirmed' },
          ].map(t => (
            <div key={t.type} style={{ padding: 14, background: 'var(--navy-900)', borderRadius: 'var(--radius-md)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{t.name}</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{t.desc}</div>
              </div>
              <span className="badge suspended">Inativo</span>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}
