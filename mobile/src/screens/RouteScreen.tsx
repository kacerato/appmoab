import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Modal,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useAuth } from '../lib/auth';
import { api } from '../lib/api';
import { useFeedback } from '../lib/feedback';
import { colors, shared } from '../styles/theme';

type ActiveTab = 'home' | 'tasks' | 'create' | 'history' | 'profile';

interface Hydrometer {
  id: string;
  code: string;
  last_reading_value: number;
  red_digits?: number | null;
  black_digits?: number | null;
  brand?: string | null;
  model?: string | null;
  location_description?: string | null;
}

interface Customer {
  id: string;
  name: string;
  address: string;
  city: string;
  hydrometers: Hydrometer[];
}

interface ReadingItem {
  id?: string;
  hydrometer_id: string;
  collaborator_id: string;
  current_value?: number;
  consumption?: number;
  captured_at: string;
  status: string;
  customer_name?: string | null;
  hydrometer_code?: string | null;
}

function getMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export default function RouteScreen() {
  const navigation = useNavigation<any>();
  const { user, logout } = useAuth();
  const { showToast } = useFeedback();
  const [activeTab, setActiveTab] = useState<ActiveTab>('home');
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [todayReadings, setTodayReadings] = useState<ReadingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastLoadedAt, setLastLoadedAt] = useState<number | null>(null);
  const [query, setQuery] = useState('');
  const [taskFilter, setTaskFilter] = useState<'pending' | 'done' | 'all'>('pending');
  const [createOpen, setCreateOpen] = useState(false);

  const openManualScan = useCallback(() => {
    navigation.navigate('Camera', { stage: 'code' });
  }, [navigation]);

  const load = useCallback(async (force = false) => {
    const now = Date.now();
    if (!force && lastLoadedAt && now - lastLoadedAt < 45000) {
      setLoading(false);
      setRefreshing(false);
      return;
    }

    if (!force) setLoading(true);
    const customersRequest = api.get<{ items: Customer[] }>('/customers?has_hydrometer=true&status=active&per_page=100&route_scope=true');
    const readingsRequest = api.get<{ items: ReadingItem[] }>('/readings?per_page=100');
    const [customersResult, readingsResult] = await Promise.allSettled([customersRequest, readingsRequest]);

    if (customersResult.status === 'fulfilled') {
      setCustomers((customersResult.value.items || []).filter(customer => customer.hydrometers?.length));
    } else {
      showToast('Falha ao carregar clientes', getMessage(customersResult.reason, 'Nao foi possivel buscar sua rota.'), 'error');
    }

    if (readingsResult.status === 'fulfilled') {
      const todayKey = new Date().toISOString().slice(0, 10);
      setTodayReadings(
        (readingsResult.value.items || []).filter(
          item => item.collaborator_id === user?.id && item.captured_at.slice(0, 10) === todayKey,
        ),
      );
    } else {
      setTodayReadings([]);
      showToast('Historico parcial', getMessage(readingsResult.reason, 'Nao foi possivel carregar as leituras de hoje.'), 'warning');
    }

    setLastLoadedAt(Date.now());
    setLoading(false);
    setRefreshing(false);
  }, [lastLoadedAt, refreshing, showToast, user?.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const routeItems = useMemo(() => {
    const byHydrometer = new Map<string, ReadingItem>();
    for (const reading of todayReadings) byHydrometer.set(reading.hydrometer_id, reading);

    return customers
      .map(customer => {
        const hydrometer = customer.hydrometers[0];
        return {
          customer,
          hydrometer,
          todayStatus: hydrometer ? byHydrometer.get(hydrometer.id) : undefined,
        };
      })
      .filter(item => item.hydrometer)
      .filter(item => {
        const search = query.trim().toLowerCase();
        if (!search) return true;
        return (
          item.customer.name.toLowerCase().includes(search) ||
          item.hydrometer.code.toLowerCase().includes(search) ||
          (item.hydrometer.location_description || '').toLowerCase().includes(search)
        );
      });
  }, [customers, query, todayReadings]);

  const stats = useMemo(() => {
    const total = routeItems.length;
    const completed = routeItems.filter(item => item.todayStatus && item.todayStatus.status !== 'rejected').length;
    return { total, pending: Math.max(total - completed, 0), completed };
  }, [routeItems]);

  const tasks = useMemo(() => {
    const mapped = routeItems.map(item => ({
      ...item,
      done: Boolean(item.todayStatus && item.todayStatus.status !== 'rejected'),
    }));
    if (taskFilter === 'pending') return mapped.filter(item => !item.done);
    if (taskFilter === 'done') return mapped.filter(item => item.done);
    return mapped;
  }, [routeItems, taskFilter]);

  const startCapture = useCallback((item: { customer: Customer; hydrometer: Hydrometer }) => {
    navigation.navigate('Camera', {
      stage: 'code',
      expectedCustomerId: item.customer.id,
      expectedCustomerName: item.customer.name,
      expectedHydrometerId: item.hydrometer.id,
      expectedHydrometerCode: item.hydrometer.code,
      lastReading: item.hydrometer.last_reading_value || 0,
      redDigits: item.hydrometer.red_digits || 3,
      blackDigits: item.hydrometer.black_digits || null,
      hydrometerBrand: item.hydrometer.brand || '',
      hydrometerModel: item.hydrometer.model || '',
      locationDescription: item.hydrometer.location_description || '',
    });
  }, [navigation]);

  const onRefresh = () => {
    setRefreshing(true);
    void load(true);
  };

  if (loading) {
    return (
      <SafeAreaView style={shared.safeArea} edges={['top', 'left', 'right']}>
        <View style={styles.loadingWrap}>
          <ActivityIndicator size="large" color={colors.accent} />
          <Text style={styles.loadingText}>Carregando rota...</Text>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={shared.safeArea} edges={['top', 'left', 'right']}>
      <View style={styles.screen}>
        {activeTab === 'home' && (
          <FlatList
            data={routeItems}
            keyExtractor={item => item.customer.id}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}
            contentContainerStyle={styles.listContent}
            ListHeaderComponent={
              <>
                <Hero userName={user?.name || 'Colaborador'} stats={stats} onLogout={logout} />
                <TextInput
                  style={styles.searchInput}
                  value={query}
                  onChangeText={setQuery}
                  placeholder="Buscar por cliente, codigo ou local"
                  placeholderTextColor={colors.textMuted}
                />
                <View style={styles.sectionHeader}>
                  <Text style={styles.sectionTitle}>Pontos da rota</Text>
                  <Text style={styles.sectionMeta}>{lastLoadedAt ? `Atualizado ${new Date(lastLoadedAt).toLocaleTimeString('pt-BR')}` : ''}</Text>
                </View>
              </>
            }
            renderItem={({ item }) => (
              <CustomerCard item={item} onPress={() => startCapture(item)} />
            )}
            ListEmptyComponent={<EmptyCard title="Nenhum ponto carregado" text="Toque em atualizar ou use a acao central para abrir a camera." />}
          />
        )}

        {activeTab === 'tasks' && (
          <FlatList
            data={tasks}
            keyExtractor={item => item.customer.id}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}
            contentContainerStyle={styles.listContent}
            ListHeaderComponent={
              <>
                <ScreenHeader eyebrow="Fila operacional" title="Minhas tarefas" subtitle="Leituras separadas por prioridade de campo." />
                <View style={styles.segmented}>
                  <Segment label="Pendentes" active={taskFilter === 'pending'} onPress={() => setTaskFilter('pending')} />
                  <Segment label="Concluidas" active={taskFilter === 'done'} onPress={() => setTaskFilter('done')} />
                  <Segment label="Todas" active={taskFilter === 'all'} onPress={() => setTaskFilter('all')} />
                </View>
              </>
            }
            renderItem={({ item }) => <TaskCard item={item} onPress={() => startCapture(item)} />}
            ListEmptyComponent={<EmptyCard title="Nada nesta fila" text="Quando houver pontos nesse status, eles aparecem aqui." />}
          />
        )}

        {activeTab === 'history' && (
          <FlatList
            data={todayReadings}
            keyExtractor={(item, index) => item.id || `${item.hydrometer_id}-${index}`}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}
            contentContainerStyle={styles.listContent}
            ListHeaderComponent={
              <ScreenHeader eyebrow="Resumo do dia" title="Historico" subtitle="Leituras enviadas, consumo registrado e status de aprovacao." />
            }
            renderItem={({ item }) => <HistoryCard item={item} />}
            ListEmptyComponent={<EmptyCard title="Nenhuma leitura hoje" text="As leituras aparecem aqui depois do envio." />}
          />
        )}

        {activeTab === 'profile' && (
          <ScrollView contentContainerStyle={styles.listContent} refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}>
            <ProfileView name={user?.name || 'Colaborador'} email={user?.email || ''} role={user?.role || ''} stats={stats} onLogout={logout} />
          </ScrollView>
        )}

        <BottomTabs
          active={activeTab}
          onTabPress={tab => {
            if (tab === 'create') {
              setCreateOpen(true);
              return;
            }
            setActiveTab(tab);
          }}
        />

        <CreateModal
          visible={createOpen}
          onClose={() => setCreateOpen(false)}
          onOpenCamera={() => {
            setCreateOpen(false);
            openManualScan();
          }}
          onOpenHistory={() => {
            setCreateOpen(false);
            setActiveTab('history');
          }}
        />
      </View>
    </SafeAreaView>
  );
}

function Hero({ userName, stats, onLogout }: { userName: string; stats: { pending: number; completed: number; total: number }; onLogout: () => void }) {
  return (
    <View style={styles.heroCard}>
      <View style={styles.neoLine} />
      <View style={styles.heroTopRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.heroEyebrow}>COMMAND CENTER</Text>
          <Text style={styles.heroTitle}>Ola, {userName.split(' ')[0]}!</Text>
          <Text style={styles.heroSubtitle}>Bem-vindo de volta ao controle.</Text>
        </View>
        <TouchableOpacity style={styles.logoutPill} onPress={onLogout}>
          <Text style={styles.logoutText}>Sair</Text>
        </TouchableOpacity>
      </View>
      <View style={styles.summaryRow}>
        <SummaryCard label="Pendentes" value={stats.pending} tone="warning" />
        <SummaryCard label="Concluidas" value={stats.completed} tone="success" />
        <SummaryCard label="Rota" value={stats.total} tone="info" />
      </View>
      <View style={styles.progressPanel}>
        <View style={styles.progressRing}>
          <Text style={styles.progressText}>{stats.total ? Math.round((stats.completed / stats.total) * 100) : 0}%</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.progressTitle}>Status da missão</Text>
          <Text style={styles.progressSub}>Leitura manual assistida por Kimi, sem travar o campo.</Text>
        </View>
      </View>
    </View>
  );
}

function ScreenHeader({ eyebrow, title, subtitle }: { eyebrow: string; title: string; subtitle: string }) {
  return (
    <View style={styles.heroCard}>
      <View style={styles.neoLine} />
      <Text style={styles.heroEyebrow}>{eyebrow}</Text>
      <Text style={styles.heroTitle}>{title}</Text>
      <Text style={styles.heroSubtitle}>{subtitle}</Text>
    </View>
  );
}

function CustomerCard({ item, onPress }: { item: { customer: Customer; hydrometer: Hydrometer; todayStatus?: ReadingItem }; onPress: () => void }) {
  return (
    <TouchableOpacity activeOpacity={0.88} style={styles.customerCard} onPress={onPress}>
      <View style={styles.neoLine} />
      <View style={styles.cardTopRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.customerName}>{item.customer.name}</Text>
          <Text style={styles.customerCode}>Codigo {item.hydrometer.code}</Text>
        </View>
        <StatusBadge status={item.todayStatus?.status || 'pending'} />
      </View>
      {!!item.hydrometer.location_description && <Text style={styles.locationText}>{item.hydrometer.location_description}</Text>}
      <Text style={styles.metaLine}>
        Mostrador: {item.hydrometer.red_digits || 3} digitos vermelhos
        {item.hydrometer.black_digits ? ` - ${item.hydrometer.black_digits} pretos` : ''}
      </Text>
      <View style={styles.rowActionButton}>
        <Text style={styles.rowActionButtonText}>Escanear</Text>
      </View>
    </TouchableOpacity>
  );
}

function TaskCard({ item, onPress }: { item: { customer: Customer; hydrometer: Hydrometer; todayStatus?: ReadingItem; done: boolean }; onPress: () => void }) {
  return (
    <TouchableOpacity style={styles.taskCard} onPress={onPress} disabled={item.done}>
      <View style={[styles.checkbox, item.done && styles.checkboxDone]}>
        <Text style={styles.checkboxText}>{item.done ? '✓' : ''}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.customerName}>{item.customer.name}</Text>
        <Text style={styles.metaLine}>Codigo {item.hydrometer.code}</Text>
      </View>
      <StatusBadge status={item.todayStatus?.status || 'pending'} />
    </TouchableOpacity>
  );
}

function HistoryCard({ item }: { item: ReadingItem }) {
  return (
    <View style={styles.customerCard}>
      <View style={styles.cardTopRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.customerName}>{item.customer_name || 'Cliente sem nome'}</Text>
          <Text style={styles.metaLine}>{item.hydrometer_code || 'Sem codigo'} - {new Date(item.captured_at).toLocaleTimeString('pt-BR')}</Text>
        </View>
        <StatusBadge status={item.status} />
      </View>
      <Text style={styles.locationText}>
        Leitura {(item.current_value || 0).toFixed(2)} m3 - Consumo {(item.consumption || 0).toFixed(2)} m3
      </Text>
    </View>
  );
}

function ProfileView({ name, email, role, stats, onLogout }: { name: string; email: string; role: string; stats: { pending: number; completed: number; total: number }; onLogout: () => void }) {
  return (
    <>
      <View style={styles.profileHero}>
        <View style={styles.avatar}><Text style={styles.avatarText}>{name.slice(0, 1).toUpperCase()}</Text></View>
        <Text style={styles.profileName}>{name}</Text>
        <Text style={styles.heroSubtitle}>{email || role}</Text>
        <View style={styles.summaryRow}>
          <SummaryCard label="Leituras" value={stats.completed} tone="success" />
          <SummaryCard label="Pendentes" value={stats.pending} tone="warning" />
          <SummaryCard label="Rota" value={stats.total} tone="info" />
        </View>
      </View>
      <View style={styles.customerCard}>
        <Text style={shared.sectionTitle}>Configuracoes</Text>
        <SettingRow label="Notificacoes" value="Ativas no painel" />
        <SettingRow label="Tema" value="AquaMoab dark" />
        <TouchableOpacity style={[shared.btnSecondary, { marginTop: 12 }]} onPress={onLogout}>
          <Text style={shared.btnSecondaryText}>Sair da conta</Text>
        </TouchableOpacity>
      </View>
    </>
  );
}

function SettingRow({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.settingRow}>
      <Text style={styles.settingLabel}>{label}</Text>
      <Text style={styles.settingValue}>{value}</Text>
    </View>
  );
}

function SummaryCard({ label, value, tone }: { label: string; value: number; tone: 'warning' | 'success' | 'info' }) {
  const palette = {
    warning: { bg: colors.warningSoft, text: colors.warning },
    success: { bg: colors.successSoft, text: colors.success },
    info: { bg: colors.accentSoft, text: colors.accent },
  }[tone];
  return (
    <View style={[styles.summaryCard, { backgroundColor: palette.bg }]}>
      <Text style={styles.summaryLabel}>{label}</Text>
      <Text style={[styles.summaryValue, { color: palette.text }]}>{value}</Text>
    </View>
  );
}

function StatusBadge({ status }: { status: string }) {
  let palette = { backgroundColor: colors.warningSoft, color: colors.warning, label: 'Pendente' };
  if (status === 'approved') palette = { backgroundColor: colors.successSoft, color: colors.success, label: 'Ok' };
  if (status === 'rejected') palette = { backgroundColor: colors.dangerSoft, color: colors.danger, label: 'Revisar' };
  return (
    <View style={[shared.badge, { backgroundColor: palette.backgroundColor }]}>
      <Text style={[shared.badgeText, { color: palette.color }]}>{palette.label}</Text>
    </View>
  );
}

function EmptyCard({ title, text }: { title: string; text: string }) {
  return (
    <View style={styles.emptyCard}>
      <Text style={styles.emptyTitle}>{title}</Text>
      <Text style={styles.emptyText}>{text}</Text>
    </View>
  );
}

function Segment({ label, active, onPress }: { label: string; active: boolean; onPress: () => void }) {
  return (
    <TouchableOpacity style={[styles.segment, active && styles.segmentActive]} onPress={onPress}>
      <Text style={[styles.segmentText, active && styles.segmentTextActive]}>{label}</Text>
    </TouchableOpacity>
  );
}

function BottomTabs({ active, onTabPress }: { active: ActiveTab; onTabPress: (tab: ActiveTab) => void }) {
  const tabs: Array<{ key: ActiveTab; label: string; icon: string }> = [
    { key: 'home', label: 'Home', icon: 'H' },
    { key: 'tasks', label: 'Tarefas', icon: 'T' },
    { key: 'create', label: 'Criar', icon: '+' },
    { key: 'history', label: 'Historico', icon: 'G' },
    { key: 'profile', label: 'Perfil', icon: 'P' },
  ];
  return (
    <View style={styles.tabBar}>
      {tabs.map(tab => {
        const isCreate = tab.key === 'create';
        const selected = active === tab.key;
        return (
          <TouchableOpacity key={tab.key} style={styles.tabItem} onPress={() => onTabPress(tab.key)}>
            <View style={[styles.tabIcon, selected && styles.tabIconActive, isCreate && styles.createIcon]}>
              {selected && <View style={styles.activeBeam} />}
              <Text style={[styles.tabIconText, (selected || isCreate) && styles.tabIconTextActive]}>{tab.icon}</Text>
            </View>
            <Text style={[styles.tabLabel, selected && styles.tabLabelActive]}>{tab.label}</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

function CreateModal({ visible, onClose, onOpenCamera, onOpenHistory }: { visible: boolean; onClose: () => void; onOpenCamera: () => void; onOpenHistory: () => void }) {
  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onClose}>
      <View style={styles.modalBackdrop}>
        <View style={styles.modalCard}>
          <View style={styles.cardTopRow}>
            <Text style={styles.modalTitle}>Nova acao</Text>
            <TouchableOpacity onPress={onClose}><Text style={styles.backText}>Fechar</Text></TouchableOpacity>
          </View>
          <View style={styles.actionGrid}>
            <ActionTile title="Scan manual" subtitle="Foto, codigo, leitura" onPress={onOpenCamera} />
            <ActionTile title="Historico" subtitle="Ver envios do dia" onPress={onOpenHistory} />
            <ActionTile title="Checklist" subtitle="Pendencias da rota" onPress={onClose} />
            <ActionTile title="Sincronizar" subtitle="Atualize puxando a tela" onPress={onClose} />
          </View>
        </View>
      </View>
    </Modal>
  );
}

function ActionTile({ title, subtitle, onPress }: { title: string; subtitle: string; onPress: () => void }) {
  return (
    <TouchableOpacity style={styles.actionTile} onPress={onPress}>
      <Text style={styles.actionTitle}>{title}</Text>
      <Text style={styles.actionSubtitle}>{subtitle}</Text>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.navy950 },
  loadingWrap: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: colors.navy950 },
  loadingText: { marginTop: 14, color: colors.textMuted, fontSize: 13 },
  listContent: { paddingHorizontal: 16, paddingBottom: 104 },
  heroCard: {
    marginTop: 10,
    marginBottom: 16,
    padding: 18,
    borderRadius: 26,
    backgroundColor: 'rgba(16, 33, 58, 0.78)',
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: colors.accent,
    shadowOffset: { width: 0, height: 12 },
    shadowOpacity: 0.14,
    shadowRadius: 28,
    elevation: 10,
    overflow: 'hidden',
  },
  neoLine: { position: 'absolute', top: 0, left: 18, right: 18, height: 1, backgroundColor: 'rgba(0,240,255,0.44)' },
  heroTopRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  heroEyebrow: { color: colors.cyan, fontSize: 11, fontWeight: '900', textTransform: 'uppercase', letterSpacing: 2 },
  heroTitle: { color: colors.textPrimary, fontSize: 31, fontWeight: '900', marginTop: 4, letterSpacing: 0 },
  heroSubtitle: { color: colors.textMuted, fontSize: 13, marginTop: 6, lineHeight: 19 },
  logoutPill: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 9,
  },
  logoutText: { color: colors.textPrimary, fontWeight: '800', fontSize: 12 },
  summaryRow: { flexDirection: 'row', gap: 10, marginTop: 16 },
  summaryCard: { flex: 1, borderRadius: 18, padding: 12, minHeight: 78, borderWidth: 1, borderColor: colors.border },
  summaryLabel: { color: colors.textMuted, fontSize: 10, fontWeight: '900', textTransform: 'uppercase', letterSpacing: 1 },
  summaryValue: { fontSize: 24, fontWeight: '900', marginTop: 6 },
  progressPanel: { marginTop: 16, padding: 14, borderRadius: 22, backgroundColor: 'rgba(7,17,31,0.62)', borderWidth: 1, borderColor: colors.border, flexDirection: 'row', gap: 14, alignItems: 'center' },
  progressRing: { width: 62, height: 62, borderRadius: 31, borderWidth: 5, borderColor: colors.accent, alignItems: 'center', justifyContent: 'center', shadowColor: colors.accent, shadowOpacity: 0.35, shadowRadius: 18 },
  progressText: { color: colors.textPrimary, fontWeight: '900', fontSize: 15 },
  progressTitle: { color: colors.textPrimary, fontWeight: '900', fontSize: 14 },
  progressSub: { color: colors.textMuted, fontSize: 12, lineHeight: 18, marginTop: 3 },
  searchInput: {
    backgroundColor: 'rgba(16, 33, 58, 0.72)',
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 22,
    color: colors.textPrimary,
    fontSize: 14,
    paddingHorizontal: 16,
    paddingVertical: 14,
    marginBottom: 16,
  },
  sectionHeader: { marginBottom: 10, flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  sectionTitle: { color: colors.textPrimary, fontSize: 19, fontWeight: '800' },
  sectionMeta: { color: colors.textMuted, fontSize: 11 },
  customerCard: {
    backgroundColor: 'rgba(16, 33, 58, 0.76)',
    borderRadius: 24,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    marginBottom: 12,
    shadowColor: colors.accent,
    shadowOpacity: 0.08,
    shadowRadius: 18,
    elevation: 6,
    overflow: 'hidden',
  },
  cardTopRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 },
  customerName: { color: colors.textPrimary, fontWeight: '900', fontSize: 17 },
  customerCode: { color: colors.cyan, fontSize: 12, fontWeight: '700', marginTop: 6 },
  metaLine: { color: colors.textMuted, fontSize: 12, marginTop: 6 },
  locationText: { color: colors.textSecondary, fontSize: 13, lineHeight: 19, marginTop: 12 },
  rowActionButton: { marginTop: 14, backgroundColor: colors.accentSoft, borderRadius: 999, paddingVertical: 14, alignItems: 'center', borderWidth: 1, borderColor: colors.borderHover },
  rowActionButtonText: { color: colors.accent, fontSize: 14, fontWeight: '900', textTransform: 'uppercase', letterSpacing: 1 },
  emptyCard: { backgroundColor: colors.navy800, borderRadius: 20, borderWidth: 1, borderColor: colors.border, padding: 18 },
  emptyTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: '800' },
  emptyText: { color: colors.textSecondary, fontSize: 13, lineHeight: 20, marginTop: 8 },
  segmented: { flexDirection: 'row', backgroundColor: colors.navy800, borderRadius: 18, padding: 5, marginBottom: 14, borderWidth: 1, borderColor: colors.border },
  segment: { flex: 1, paddingVertical: 11, alignItems: 'center', borderRadius: 14 },
  segmentActive: { backgroundColor: colors.accentSoft },
  segmentText: { color: colors.textMuted, fontWeight: '800', fontSize: 12 },
  segmentTextActive: { color: colors.accent },
  taskCard: {
    backgroundColor: colors.navy800,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    marginBottom: 12,
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  checkbox: { width: 28, height: 28, borderRadius: 10, borderWidth: 2, borderColor: colors.border, alignItems: 'center', justifyContent: 'center' },
  checkboxDone: { backgroundColor: colors.successSoft, borderColor: colors.success },
  checkboxText: { color: colors.success, fontWeight: '900' },
  profileHero: {
    marginTop: 10,
    marginBottom: 16,
    padding: 22,
    borderRadius: 24,
    backgroundColor: 'rgba(9,19,33,0.94)',
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
  },
  avatar: { width: 76, height: 76, borderRadius: 24, backgroundColor: colors.accentSoft, alignItems: 'center', justifyContent: 'center', marginBottom: 12 },
  avatarText: { color: colors.cyan, fontSize: 34, fontWeight: '900' },
  profileName: { color: colors.textPrimary, fontSize: 24, fontWeight: '900' },
  settingRow: { paddingVertical: 13, borderBottomWidth: 1, borderBottomColor: colors.border, flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
  settingLabel: { color: colors.textPrimary, fontWeight: '800' },
  settingValue: { color: colors.textMuted, fontSize: 12 },
  tabBar: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
    height: 82,
    backgroundColor: colors.sidebarNavy,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    flexDirection: 'row',
    paddingTop: 8,
    paddingHorizontal: 8,
  },
  tabItem: { flex: 1, alignItems: 'center' },
  tabIcon: { width: 34, height: 34, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  tabIconActive: { backgroundColor: colors.accentSoft, shadowColor: colors.accent, shadowOpacity: 0.45, shadowRadius: 12 },
  createIcon: { backgroundColor: colors.accent, width: 52, height: 52, borderRadius: 26, marginTop: -16, borderWidth: 4, borderColor: 'rgba(0,240,255,0.25)' },
  activeBeam: { position: 'absolute', bottom: -8, width: 22, height: 3, borderRadius: 2, backgroundColor: colors.accent },
  tabIconText: { color: colors.textMuted, fontWeight: '900', fontSize: 14 },
  tabIconTextActive: { color: '#fff' },
  tabLabel: { color: colors.textMuted, fontSize: 10, fontWeight: '800', marginTop: 3 },
  tabLabelActive: { color: colors.textPrimary },
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(0,0,0,0.62)', justifyContent: 'flex-end', padding: 16 },
  modalCard: { backgroundColor: 'rgba(11,23,40,0.96)', borderRadius: 24, borderWidth: 1, borderColor: colors.border, padding: 18, marginBottom: 70 },
  modalTitle: { color: colors.textPrimary, fontSize: 20, fontWeight: '900' },
  backText: { color: colors.cyan, fontWeight: '900' },
  actionGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 18 },
  actionTile: { width: '48%', backgroundColor: colors.navy800, borderRadius: 18, borderWidth: 1, borderColor: colors.border, padding: 14, minHeight: 92 },
  actionTitle: { color: colors.textPrimary, fontWeight: '900', fontSize: 15 },
  actionSubtitle: { color: colors.textMuted, fontSize: 12, lineHeight: 18, marginTop: 8 },
});
