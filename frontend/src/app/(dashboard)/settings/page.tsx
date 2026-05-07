'use client';

import Header from '@/components/Header';
import { Settings as SettingsIcon, Database, Globe, Key, Server } from 'lucide-react';

export default function SettingsPage() {
  return (
    <>
      <Header title="Configurações" subtitle="Parâmetros do sistema" />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <SettingCard
          icon={<Database size={18} />}
          title="Banco de Dados"
          desc="Neon PostgreSQL Serverless"
          status="Conectado"
          statusColor="var(--success)"
        />
        <SettingCard
          icon={<Key size={18} />}
          title="Banco Inter"
          desc="API Cobrança V3 — Sandbox"
          status="Configurado"
          statusColor="var(--success)"
        />
        <SettingCard
          icon={<Globe size={18} />}
          title="WhatsApp"
          desc="Cloud API — Aguardando número"
          status="Desativado"
          statusColor="var(--warning)"
        />
        <SettingCard
          icon={<Server size={18} />}
          title="Kimi K2.6 Vision"
          desc="OCR de hidrômetros — Moonshot AI"
          status="Configurado"
          statusColor="var(--success)"
        />
      </div>

      <div className="card" style={{ marginTop: 24 }}>
        <div className="card-header"><span className="card-title">Informações do Sistema</span></div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, fontSize: 13, color: 'var(--text-secondary)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Versão</span><span style={{ fontWeight: 600 }}>1.0.0</span></div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Backend</span><span style={{ fontWeight: 600 }}>FastAPI (Python)</span></div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Frontend</span><span style={{ fontWeight: 600 }}>Next.js 15</span></div>
          <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Deploy</span><span style={{ fontWeight: 600 }}>Vercel + Render/Railway</span></div>
        </div>
      </div>
    </>
  );
}

function SettingCard({ icon, title, desc, status, statusColor }: {
  icon: React.ReactNode; title: string; desc: string; status: string; statusColor: string;
}) {
  return (
    <div className="card" style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
      <div className="kpi-icon blue" style={{ width: 44, height: 44, flexShrink: 0 }}>{icon}</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontWeight: 700, fontSize: 14 }}>{title}</div>
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{desc}</div>
      </div>
      <div style={{ fontSize: 12, fontWeight: 600, color: statusColor }}>{status}</div>
    </div>
  );
}
