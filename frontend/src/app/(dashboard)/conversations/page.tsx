'use client';

import { useEffect, useState } from 'react';
import Header from '@/components/Header';
import { api } from '@/lib/api';
import { Loader2, MessageCircle } from 'lucide-react';

interface Conversation {
  phone: string;
  customer_id: string | null;
  customer_name: string | null;
  last_message: string;
  last_direction: string;
  last_at: string;
  total_messages: number;
}

interface WhatsAppMessage {
  id: string;
  phone: string;
  direction: string;
  body: string;
  status: string;
  created_at: string;
}

export default function ConversationsPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [messages, setMessages] = useState<WhatsAppMessage[]>([]);
  const [selectedPhone, setSelectedPhone] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [messagesLoading, setMessagesLoading] = useState(false);

  useEffect(() => {
    api.get<Conversation[]>('/whatsapp/conversations')
      .then(items => {
        setConversations(items);
        if (items[0]) setSelectedPhone(items[0].phone);
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    if (!selectedPhone) return;
    setMessagesLoading(true);
    api.get<WhatsAppMessage[]>(`/whatsapp/conversations/${encodeURIComponent(selectedPhone)}/messages`)
      .then(setMessages)
      .catch(console.error)
      .finally(() => setMessagesLoading(false));
  }, [selectedPhone]);

  const selected = conversations.find(item => item.phone === selectedPhone);

  return (
    <>
      <Header title="Conversas" subtitle="Mensagens recebidas pelo WhatsApp conectado" />

      <div style={{ display: 'grid', gridTemplateColumns: '360px 1fr', gap: 16, alignItems: 'start' }}>
        <div className="card">
          <div className="card-header">
            <span className="card-title">Clientes e números</span>
          </div>
          {loading ? (
            <div className="loading-page" style={{ minHeight: 160 }}>
              <Loader2 size={18} className="spinner" />
            </div>
          ) : !conversations.length ? (
            <div className="empty-state" style={{ padding: 28 }}>
              <MessageCircle size={24} />
              <p>Nenhuma conversa recebida ainda.</p>
            </div>
          ) : (
            <div style={{ display: 'grid', gap: 8 }}>
              {conversations.map(item => (
                <button
                  key={item.phone}
                  type="button"
                  onClick={() => setSelectedPhone(item.phone)}
                  style={{
                    textAlign: 'left',
                    border: '1px solid var(--border)',
                    background: selectedPhone === item.phone ? 'var(--accent-soft)' : 'var(--navy-900)',
                    borderRadius: 'var(--radius-md)',
                    padding: 12,
                    cursor: 'pointer',
                  }}
                >
                  <div style={{ fontWeight: 700, fontSize: 13 }}>{item.customer_name || item.phone}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>{item.last_message}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 6 }}>
                    {item.total_messages} mensagem(ns)
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="card" style={{ minHeight: 420 }}>
          <div className="card-header">
            <span className="card-title">{selected?.customer_name || selected?.phone || 'Conversa'}</span>
            {selected && <span className="badge active">{selected.phone}</span>}
          </div>

          {messagesLoading ? (
            <div className="loading-page" style={{ minHeight: 220 }}>
              <Loader2 size={18} className="spinner" />
            </div>
          ) : !selectedPhone ? (
            <div className="empty-state" style={{ padding: 40 }}>
              <p>Selecione uma conversa para visualizar o histórico.</p>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {messages.map(message => (
                <div
                  key={message.id}
                  style={{
                    alignSelf: message.direction === 'outbound' ? 'flex-end' : 'flex-start',
                    maxWidth: '72%',
                    padding: 12,
                    borderRadius: 'var(--radius-md)',
                    background: message.direction === 'outbound' ? 'var(--accent)' : 'var(--navy-900)',
                    color: message.direction === 'outbound' ? '#fff' : 'var(--text-primary)',
                  }}
                >
                  <div style={{ fontSize: 13 }}>{message.body}</div>
                  <div style={{ fontSize: 11, opacity: 0.72, marginTop: 6 }}>
                    {new Date(message.created_at).toLocaleString('pt-BR')}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
}
