'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Header from '@/components/Header';
import { useAppFeedback } from '@/components/AppFeedbackProvider';
import { api } from '@/lib/api';
import {
  AlertTriangle,
  Check,
  CheckCheck,
  Loader2,
  MessageCircle,
  Phone,
  Plus,
  Reply,
  Search,
  Send,
  UserRound,
  X,
} from 'lucide-react';

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
  customer_id: string | null;
  phone: string;
  direction: string;
  body: string;
  status: string;
  external_message_id: string | null;
  payload: {
    quoted_message_id?: string;
    quoted_body?: string;
    quoted_direction?: string;
    quoted_created_at?: string;
    sent_text?: string;
  } | null;
  created_at: string;
}

interface SendMessageResponse {
  message: WhatsAppMessage;
  whatsapp_status: string;
  detail: string | null;
}

interface CustomerOption {
  id: string;
  name: string;
  phone: string | null;
  status: string;
}

interface CustomerListResponse {
  items: CustomerOption[];
  total: number;
  page: number;
  per_page: number;
}

function formatDate(value: string) {
  return new Date(value).toLocaleString('pt-BR', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function formatPhone(phone: string) {
  const digits = phone.replace(/\D/g, '');
  if (digits.length === 13) {
    return `+${digits.slice(0, 2)} ${digits.slice(2, 4)} ${digits.slice(4, 9)}-${digits.slice(9)}`;
  }
  if (digits.length === 12) {
    return `+${digits.slice(0, 2)} ${digits.slice(2, 4)} ${digits.slice(4, 8)}-${digits.slice(8)}`;
  }
  return phone;
}

function truncate(value: string, size = 92) {
  return value.length > size ? `${value.slice(0, size - 3)}...` : value;
}

function deliveryTitle(status: string) {
  const map: Record<string, string> = {
    sent: 'Enviada',
    delivered: 'Entregue',
    read: 'Visualizada',
    failed: 'Falhou',
    disabled: 'WhatsApp desativado',
  };
  return map[status] || status;
}

export default function ConversationsPage() {
  const { notify } = useAppFeedback();
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [customers, setCustomers] = useState<CustomerOption[]>([]);
  const [messages, setMessages] = useState<WhatsAppMessage[]>([]);
  const [selectedPhone, setSelectedPhone] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [customersLoading, setCustomersLoading] = useState(true);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [sending, setSending] = useState(false);
  const [composer, setComposer] = useState('');
  const [quoted, setQuoted] = useState<WhatsAppMessage | null>(null);
  const [showNewConversation, setShowNewConversation] = useState(false);
  const [newCustomerId, setNewCustomerId] = useState('');
  const [newPhone, setNewPhone] = useState('');
  const [newText, setNewText] = useState('');
  const selectedPhoneRef = useRef<string | null>(null);

  useEffect(() => {
    selectedPhoneRef.current = selectedPhone;
  }, [selectedPhone]);

  const loadMessages = useCallback((phone: string, showLoading = true) => {
    if (showLoading) setMessagesLoading(true);
    api.get<WhatsAppMessage[]>(`/whatsapp/conversations/${encodeURIComponent(phone)}/messages`, { skipCache: true })
      .then(setMessages)
      .catch(err => notify('Falha ao carregar conversa', err instanceof Error ? err.message : 'Erro ao buscar mensagens.', 'error'))
      .finally(() => {
        if (showLoading) setMessagesLoading(false);
      });
  }, [notify]);

  const loadConversations = useCallback((phoneToSelect?: string, keepSelection = false, silentMessages = false) => {
    api.get<Conversation[]>('/whatsapp/conversations', { skipCache: true })
      .then(items => {
        setConversations(items);
        const currentPhone = selectedPhoneRef.current;
        const selectedStillExists = currentPhone ? items.some(item => item.phone === currentPhone) : false;
        const nextPhone = phoneToSelect || (keepSelection && selectedStillExists ? currentPhone : items[0]?.phone || null);
        setSelectedPhone(nextPhone);
        if (nextPhone) {
          loadMessages(nextPhone, !silentMessages);
        } else {
          setMessages([]);
        }
      })
      .catch(err => notify('Falha ao carregar conversas', err instanceof Error ? err.message : 'Erro ao buscar conversas.', 'error'))
      .finally(() => setLoading(false));
  }, [loadMessages, notify]);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  useEffect(() => {
    const interval = window.setInterval(() => {
      if (document.visibilityState === 'visible') {
        loadConversations(undefined, true, true);
      }
    }, 6000);
    return () => window.clearInterval(interval);
  }, [loadConversations]);

  useEffect(() => {
    api.get<CustomerListResponse>('/customers?per_page=2000')
      .then(response => setCustomers(response.items))
      .catch(err => notify('Falha ao carregar clientes', err instanceof Error ? err.message : 'Erro ao buscar clientes.', 'error'))
      .finally(() => setCustomersLoading(false));
  }, [notify]);

  const selected = conversations.find(item => item.phone === selectedPhone);
  const customersWithPhone = customers.filter(customer => customer.phone?.trim());
  const selectedCustomer = customers.find(customer => customer.id === newCustomerId);
  const filteredConversations = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return conversations;
    return conversations.filter(item => {
      const haystack = `${item.customer_name || ''} ${item.phone} ${item.last_message}`.toLowerCase();
      return haystack.includes(term);
    });
  }, [conversations, search]);

  const handleSelectConversation = (phone: string) => {
    setSelectedPhone(phone);
    setQuoted(null);
    loadMessages(phone);
  };

  const handleSend = () => {
    if (!selectedPhone || !composer.trim()) return;
    setSending(true);
    api.post<SendMessageResponse>('/whatsapp/messages', {
      phone: selectedPhone,
      text: composer,
      quoted_message_id: quoted?.id || null,
    })
      .then(response => {
        setComposer('');
        setQuoted(null);
        setMessages(current => [...current, response.message]);
        loadConversations(response.message.phone);
        notify(
          response.whatsapp_status === 'sent' ? 'Mensagem enviada' : 'Mensagem registrada',
          response.detail || 'O historico da conversa foi atualizado.',
          response.whatsapp_status === 'sent' ? 'success' : 'warning',
        );
      })
      .catch(err => notify('Falha ao enviar mensagem', err instanceof Error ? err.message : 'Erro ao enviar pelo WhatsApp.', 'error'))
      .finally(() => setSending(false));
  };

  const handleStartConversation = () => {
    if (!newText.trim()) {
      notify('Mensagem vazia', 'Escreva a primeira mensagem da conversa.', 'warning');
      return;
    }
    if (!newCustomerId && !newPhone.trim()) {
      notify('Destino obrigatorio', 'Escolha um cliente ou informe um telefone.', 'warning');
      return;
    }

    setSending(true);
    api.post<SendMessageResponse>('/whatsapp/messages', {
      customer_id: newCustomerId || null,
      phone: newCustomerId ? null : newPhone,
      text: newText,
    })
      .then(response => {
        setShowNewConversation(false);
        setNewCustomerId('');
        setNewPhone('');
        setNewText('');
        setQuoted(null);
        loadConversations(response.message.phone);
        notify(
          response.whatsapp_status === 'sent' ? 'Conversa iniciada' : 'Conversa registrada',
          response.detail || 'A mensagem foi adicionada ao historico.',
          response.whatsapp_status === 'sent' ? 'success' : 'warning',
        );
      })
      .catch(err => notify('Falha ao iniciar conversa', err instanceof Error ? err.message : 'Erro ao enviar pelo WhatsApp.', 'error'))
      .finally(() => setSending(false));
  };

  return (
    <>
      <Header title="Conversas" subtitle="Atendimento WhatsApp com historico, cliente e respostas" />

      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(300px, 380px) minmax(0, 1fr)', gap: 16, alignItems: 'stretch' }}>
        <div className="card" style={{ padding: 0, overflow: 'hidden', minHeight: 640 }}>
          <div style={{ padding: 20, borderBottom: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginBottom: 14 }}>
              <div>
                <div style={{ fontSize: 15, fontWeight: 800 }}>Conversas</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>{conversations.length} atendimento(s)</div>
              </div>
              <button className="btn btn-primary btn-sm" type="button" onClick={() => setShowNewConversation(true)}>
                <Plus size={14} />
                Nova
              </button>
            </div>
            <div className="search-box" style={{ maxWidth: 'none' }}>
              <Search />
              <input
                value={search}
                onChange={event => setSearch(event.target.value)}
                placeholder="Buscar cliente, telefone ou mensagem"
              />
            </div>
          </div>

          {loading ? (
            <div className="loading-page" style={{ minHeight: 360 }}>
              <Loader2 size={18} className="spinner" />
            </div>
          ) : !filteredConversations.length ? (
            <div className="empty-state" style={{ minHeight: 360 }}>
              <MessageCircle size={28} />
              <p>Nenhuma conversa encontrada.</p>
              <button className="btn btn-secondary btn-sm" type="button" onClick={() => setShowNewConversation(true)}>
                Iniciar conversa
              </button>
            </div>
          ) : (
            <div style={{ display: 'grid', maxHeight: 560, overflowY: 'auto' }}>
              {filteredConversations.map(item => {
                const active = selectedPhone === item.phone;
                return (
                  <button
                    key={item.phone}
                    type="button"
                    onClick={() => handleSelectConversation(item.phone)}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '36px minmax(0, 1fr)',
                      gap: 12,
                      textAlign: 'left',
                      border: 0,
                      borderBottom: '1px solid var(--border)',
                      background: active ? 'var(--accent-soft)' : 'transparent',
                      padding: '14px 18px',
                      cursor: 'pointer',
                      fontFamily: 'inherit',
                    }}
                  >
                    <span style={{
                      width: 36,
                      height: 36,
                      borderRadius: 12,
                      display: 'inline-flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      background: active ? 'var(--accent)' : 'var(--blue-50)',
                      color: active ? '#fff' : 'var(--accent)',
                    }}>
                      {item.customer_name ? <UserRound size={18} /> : <Phone size={18} />}
                    </span>
                    <span style={{ minWidth: 0 }}>
                      <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                        <span style={{ fontWeight: 800, fontSize: 13.5, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {item.customer_name || formatPhone(item.phone)}
                        </span>
                        <span style={{ fontSize: 10.5, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{formatDate(item.last_at)}</span>
                      </span>
                      <span style={{ display: 'block', fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>{formatPhone(item.phone)}</span>
                      <span style={{ display: 'block', fontSize: 12.5, color: 'var(--text-secondary)', marginTop: 6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {item.last_direction === 'outbound' ? 'Voce: ' : ''}{item.last_message}
                      </span>
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="card" style={{ padding: 0, minHeight: 640, overflow: 'hidden', display: 'grid', gridTemplateRows: 'auto 1fr auto' }}>
          <div style={{ padding: '18px 22px', borderBottom: '1px solid var(--border)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 14 }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 16, fontWeight: 800, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {selected?.customer_name || (selected ? formatPhone(selected.phone) : 'Selecione uma conversa')}
              </div>
              {selected && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 5 }}>
                  <span className="badge active">{formatPhone(selected.phone)}</span>
                  <span className="badge suspended">{selected.total_messages} mensagens</span>
                </div>
              )}
            </div>
            <MessageCircle size={22} style={{ color: 'var(--accent)' }} />
          </div>

          <div style={{ padding: 20, overflowY: 'auto', background: 'linear-gradient(180deg, var(--blue-50), transparent 170px)' }}>
            {messagesLoading ? (
              <div className="loading-page" style={{ minHeight: 300 }}>
                <Loader2 size={18} className="spinner" />
              </div>
            ) : !selectedPhone ? (
              <div className="empty-state" style={{ minHeight: 360 }}>
                <MessageCircle size={28} />
                <p>Escolha uma conversa ou inicie um atendimento com um cliente.</p>
              </div>
            ) : !messages.length ? (
              <div className="empty-state" style={{ minHeight: 360 }}>
                <MessageCircle size={28} />
                <p>Historico vazio para este numero.</p>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {messages.map(message => {
                  const outbound = message.direction === 'outbound';
                  const failed = message.status === 'failed';
                  const read = message.status === 'read';
                  const delivered = message.status === 'delivered';
                  return (
                    <div key={message.id} style={{ alignSelf: outbound ? 'flex-end' : 'flex-start', maxWidth: '76%' }}>
                      <div
                        style={{
                          padding: 12,
                          borderRadius: outbound ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                          background: outbound ? 'var(--accent)' : 'var(--bg-card)',
                          color: outbound ? '#fff' : 'var(--text-primary)',
                          border: outbound ? '1px solid var(--accent)' : '1px solid var(--border)',
                          boxShadow: 'var(--shadow-sm)',
                        }}
                      >
                        {message.payload?.quoted_body && (
                          <div
                            style={{
                              padding: '8px 10px',
                              borderLeft: outbound ? '3px solid rgba(255,255,255,0.7)' : '3px solid var(--accent)',
                              borderRadius: 8,
                              background: outbound ? 'rgba(255,255,255,0.14)' : 'var(--accent-soft)',
                              marginBottom: 8,
                              fontSize: 12,
                              lineHeight: 1.45,
                            }}
                          >
                            {truncate(message.payload.quoted_body, 160)}
                          </div>
                        )}
                        <div style={{ fontSize: 14, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>{message.body}</div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, fontSize: 11, opacity: 0.72, marginTop: 8 }}>
                          <span>{formatDate(message.created_at)}</span>
                          {outbound && (
                            <span title={deliveryTitle(message.status)} style={{ display: 'inline-flex', color: read ? '#7dd3fc' : 'inherit' }}>
                              {failed ? <AlertTriangle size={13} /> : delivered || read ? <CheckCheck size={13} /> : <Check size={13} />}
                            </span>
                          )}
                        </div>
                      </div>
                      <button
                        className="btn btn-ghost btn-sm"
                        type="button"
                        onClick={() => setQuoted(message)}
                        style={{ marginTop: 4, padding: '4px 8px', fontSize: 11 }}
                      >
                        <Reply size={12} />
                        Responder
                      </button>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div style={{ padding: 18, borderTop: '1px solid var(--border)', background: 'var(--bg-card)' }}>
            {quoted && (
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10, padding: 10, borderRadius: 12, background: 'var(--accent-soft)', marginBottom: 10 }}>
                <Reply size={15} style={{ color: 'var(--accent)', marginTop: 2 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 11, fontWeight: 800, color: 'var(--accent)', textTransform: 'uppercase', letterSpacing: 0.4 }}>Respondendo mensagem</div>
                  <div style={{ fontSize: 12.5, color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {quoted.body}
                  </div>
                </div>
                <button className="btn btn-ghost btn-icon" type="button" onClick={() => setQuoted(null)} aria-label="Remover resposta">
                  <X size={14} />
                </button>
              </div>
            )}
            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) auto', gap: 10, alignItems: 'end' }}>
              <textarea
                className="form-textarea"
                value={composer}
                onChange={event => setComposer(event.target.value)}
                placeholder={selectedPhone ? 'Digite uma mensagem' : 'Selecione uma conversa para responder'}
                disabled={!selectedPhone || sending}
                style={{ minHeight: 54, maxHeight: 140 }}
              />
              <button className="btn btn-primary" type="button" onClick={handleSend} disabled={!selectedPhone || !composer.trim() || sending}>
                {sending ? <Loader2 size={16} className="spinner" /> : <Send size={16} />}
                Enviar
              </button>
            </div>
          </div>
        </div>
      </div>

      {showNewConversation && (
        <div className="modal-overlay">
          <div className="modal" style={{ maxWidth: 560 }}>
            <div className="modal-header">
              <div>
                <div className="modal-title">Nova conversa</div>
                <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>Escolha um cliente com telefone ou informe um numero avulso.</div>
              </div>
              <button className="btn btn-ghost btn-icon" type="button" onClick={() => setShowNewConversation(false)} aria-label="Fechar">
                <X size={18} />
              </button>
            </div>

            <div style={{ display: 'grid', gap: 16 }}>
              <div className="form-group">
                <label className="form-label" htmlFor="customer_id">Cliente</label>
                <select
                  id="customer_id"
                  className="form-select"
                  value={newCustomerId}
                  onChange={event => setNewCustomerId(event.target.value)}
                  disabled={customersLoading}
                >
                  <option value="">{customersLoading ? 'Carregando clientes...' : 'Selecionar cliente'}</option>
                  {customersWithPhone.map(customer => (
                    <option key={customer.id} value={customer.id}>
                      {customer.name} - {customer.phone}
                    </option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="phone">Telefone avulso</label>
                <input
                  id="phone"
                  className="form-input"
                  value={newCustomerId ? selectedCustomer?.phone || '' : newPhone}
                  onChange={event => setNewPhone(event.target.value)}
                  placeholder="87981327592"
                  disabled={Boolean(newCustomerId)}
                />
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="message">Mensagem</label>
                <textarea
                  id="message"
                  className="form-textarea"
                  value={newText}
                  onChange={event => setNewText(event.target.value)}
                  placeholder="Digite a primeira mensagem"
                  style={{ minHeight: 130 }}
                />
              </div>
            </div>

            <div className="modal-footer">
              <button className="btn btn-secondary" type="button" onClick={() => setShowNewConversation(false)}>Cancelar</button>
              <button className="btn btn-primary" type="button" onClick={handleStartConversation} disabled={sending || !newText.trim() || (!newCustomerId && !newPhone.trim())}>
                {sending ? <Loader2 size={16} className="spinner" /> : <Send size={16} />}
                Enviar
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
