import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  AppState,
  FlatList,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useFocusEffect, useNavigation } from '@react-navigation/native';
import * as SecureStore from 'expo-secure-store';
import Svg, { Circle, Line, Path, Rect } from 'react-native-svg';
import { useAuth } from '../lib/auth';
import { api } from '../lib/api';
import { useFeedback } from '../lib/feedback';
import { useMobileTheme } from '../lib/mobile-theme';
import { formatMeterReading } from '../lib/meter-reading';
import { ROUTE_CACHE_KEY } from '../lib/route-cache';
import { colors, shared } from '../styles/theme';

type ActiveTab = 'home' | 'tasks' | 'create' | 'history' | 'profile';

interface Hydrometer {
  id: string;
  code: string;
  qr_code_token?: string | null;
  last_reading_value: number;
  red_digits?: number | null;
  black_digits?: number | null;
  brand?: string | null;
  model?: string | null;
  location_description?: string | null;
  last_reading_date?: string | null;
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
  current_value?: number | null;
  consumption?: number | null;
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
  const { mode, setMode } = useMobileTheme();
  styles = useMemo(() => createRouteStyles(), [mode]);
  const [activeTab, setActiveTab] = useState<ActiveTab>('home');
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [todayReadings, setTodayReadings] = useState<ReadingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [lastLoadedAt, setLastLoadedAt] = useState<number | null>(null);
  const lastLoadedAtRef = useRef<number | null>(null);
  const loadInFlightRef = useRef<Promise<void> | null>(null);
  const [query, setQuery] = useState('');
  const [taskFilter, setTaskFilter] = useState<'pending' | 'done' | 'all'>('pending');

  const openManualScan = useCallback(() => {
    navigation.navigate('Camera', { stage: 'code' });
  }, [navigation]);

  const saveRouteCache = useCallback(async (nextCustomers: Customer[], nextReadings: ReadingItem[]) => {
    await SecureStore.setItemAsync(ROUTE_CACHE_KEY, JSON.stringify({
      customers: nextCustomers,
      todayReadings: nextReadings,
      savedAt: Date.now(),
    })).catch(() => undefined);
  }, []);

  const load = useCallback(async (force = false, notifyFailure = false) => {
    const now = Date.now();
    if (!force && lastLoadedAtRef.current && now - lastLoadedAtRef.current < 45000) {
      setLoading(false);
      setRefreshing(false);
      return;
    }

    // The route can be resumed by both navigation and AppState. Reuse the
    // current request so a wake-up never creates competing API calls.
    if (loadInFlightRef.current) return loadInFlightRef.current;

    if (!force && !lastLoadedAtRef.current) setLoading(true);
    const request = (async () => {
      const customersRequest = api.get<{ items: Customer[] }>('/customers?has_hydrometer=true&status=active&per_page=2000&route_scope=true');
      const readingsRequest = api.get<{ items: ReadingItem[] }>('/readings?per_page=100');
      const [customersResult, readingsResult] = await Promise.allSettled([customersRequest, readingsRequest]);

      let nextCustomers: Customer[] | null = null;
      let nextReadings: ReadingItem[] | null = null;
      if (customersResult.status === 'fulfilled') {
        nextCustomers = (customersResult.value.items || []).filter(customer => customer.hydrometers?.length);
        setCustomers(nextCustomers);
      } else if (notifyFailure) {
        showToast('Falha ao carregar clientes', getMessage(customersResult.reason, 'Nao foi possivel buscar sua rota.'), 'error');
      }

      if (readingsResult.status === 'fulfilled') {
        const monthKey = new Date().toISOString().slice(0, 7);
        nextReadings = (readingsResult.value.items || []).filter(
          item => item.collaborator_id === user?.id && item.captured_at.slice(0, 7) === monthKey,
        );
        setTodayReadings(nextReadings);
      } else if (notifyFailure) {
        showToast('Historico parcial', getMessage(readingsResult.reason, 'Nao foi possivel carregar as leituras deste ciclo.'), 'warning');
      }

      if (nextCustomers && nextReadings) {
        void saveRouteCache(nextCustomers, nextReadings);
      }
      if (nextCustomers) {
        const loadedAt = Date.now();
        lastLoadedAtRef.current = loadedAt;
        setLastLoadedAt(loadedAt);
      }
      setLoading(false);
      setRefreshing(false);
    })();

    loadInFlightRef.current = request;
    try {
      await request;
    } finally {
      if (loadInFlightRef.current === request) loadInFlightRef.current = null;
    }
  }, [saveRouteCache, showToast, user?.id]);

  useEffect(() => {
    let mounted = true;
    const hydrate = async () => {
      const cached = await SecureStore.getItemAsync(ROUTE_CACHE_KEY).catch(() => null);
      if (cached && mounted) {
        try {
          const parsed = JSON.parse(cached) as { customers?: Customer[]; todayReadings?: ReadingItem[]; savedAt?: number };
          setCustomers(parsed.customers || []);
          setTodayReadings(parsed.todayReadings || []);
          const savedAt = parsed.savedAt || Date.now();
          lastLoadedAtRef.current = savedAt;
          setLastLoadedAt(savedAt);
          setLoading(false);
        } catch {
          // Ignore invalid cache and load from the API.
        }
      }
      if (mounted) void load(true);
    };
    void hydrate();
    return () => {
      mounted = false;
    };
  }, [load]);

  useFocusEffect(
    useCallback(() => {
      void load();
    }, [load]),
  );

  useEffect(() => {
    const subscription = AppState.addEventListener('change', state => {
      if (state === 'active') {
        void load();
      }
    });
    return () => subscription.remove();
  }, [load]);

  const routeItems = useMemo(() => {
    const byHydrometer = new Map<string, ReadingItem>();
    for (const reading of todayReadings) {
      const previous = byHydrometer.get(reading.hydrometer_id);
      if (!previous || reading.captured_at > previous.captured_at) {
        byHydrometer.set(reading.hydrometer_id, reading);
      }
    }

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
    const installations = routeItems.filter(item => !item.hydrometer.last_reading_date).length;
    return { total, pending: Math.max(total - completed, 0), completed, installations };
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
      expectedQrCodeToken: item.hydrometer.qr_code_token || null,
      lastReading: item.hydrometer.last_reading_value || 0,
      redDigits: item.hydrometer.red_digits || 3,
      blackDigits: item.hydrometer.black_digits || null,
      hydrometerBrand: item.hydrometer.brand || '',
      hydrometerModel: item.hydrometer.model || '',
      locationDescription: item.hydrometer.location_description || '',
      isInstallation: !item.hydrometer.last_reading_date,
    });
  }, [navigation]);

  const onRefresh = () => {
    setRefreshing(true);
    void load(true, true);
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
            <ProfileView
              name={user?.name || 'Colaborador'}
              email={user?.email || ''}
              role={user?.role || ''}
              stats={stats}
              themeMode={mode}
              onThemeChange={nextMode => void setMode(nextMode)}
              onLogout={logout}
            />
          </ScrollView>
        )}

        {user ? (
          <TouchableOpacity
            style={styles.floatingDevButton}
            onPress={() => navigation.navigate('DevVisionTest')}
          >
            <Svg width={22} height={22} viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">
              <Path d="m8 2 1.88 1.88" />
              <Path d="M14.12 3.88 16 2" />
              <Path d="M9 7.13v-1a3.001 3.001 0 1 1 6 0v1" />
              <Rect x="6" y="7" width="12" height="12" rx="6" />
              <Path d="M4 10h2" />
              <Path d="M18 10h2" />
              <Path d="M4 14h2" />
              <Path d="M18 14h2" />
              <Path d="m5 18 1.5-1.5" />
              <Path d="M17.5 16.5 19 18" />
            </Svg>
          </TouchableOpacity>
        ) : null}

        <BottomTabs
          active={activeTab}
          onTabPress={tab => {
            if (tab === 'create') {
              openManualScan();
              return;
            }
            setActiveTab(tab);
          }}
        />
      </View>
    </SafeAreaView>
  );
}

function Hero({ userName, stats, onLogout }: { userName: string; stats: { pending: number; completed: number; total: number; installations: number }; onLogout: () => void }) {
  return (
    <View style={styles.heroCard}>
      <View style={styles.neoLine} />
      <View style={styles.heroTopRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.heroEyebrow}>Rota operacional</Text>
          <Text style={styles.heroTitle}>Olá, {userName.split(' ')[0]}</Text>
          <Text style={styles.heroSubtitle}>Instalações, leituras pendentes e histórico do dia.</Text>
        </View>
        <TouchableOpacity style={styles.logoutPill} onPress={onLogout}>
          <Text style={styles.logoutText}>Sair</Text>
        </TouchableOpacity>
      </View>
      <View style={styles.summaryRow}>
        <SummaryCard label="Pendentes" value={stats.pending} tone="warning" />
        <SummaryCard label="Concluidas" value={stats.completed} tone="success" />
        <SummaryCard label="Instalacoes" value={stats.installations} tone="info" />
      </View>
      <View style={styles.progressPanel}>
        <View style={styles.progressRing}>
          <Text style={styles.progressText}>{stats.total ? Math.round((stats.completed / stats.total) * 100) : 0}%</Text>
        </View>
        <View style={{ flex: 1 }}>
          <Text style={styles.progressTitle}>Progresso de hoje</Text>
          <Text style={styles.progressSub}>Faça a leitura, confira o valor e envie com foto, hora e localização.</Text>
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
  const isInstallation = !item.hydrometer.last_reading_date;
  const locked = Boolean(item.todayStatus && item.todayStatus.status !== 'rejected');
  const actionLabel = locked
    ? item.todayStatus?.status === 'approved'
      ? 'Concluido'
      : 'Em revisao'
    : isInstallation ? 'Iniciar instalacao' : 'Escanear';
  return (
    <TouchableOpacity activeOpacity={0.88} style={[styles.customerCard, locked && styles.customerCardLocked]} onPress={onPress} disabled={locked}>
      <View style={styles.neoLine} />
      <View style={styles.cardTopRow}>
        <View style={{ flex: 1 }}>
          <Text style={styles.customerName}>{item.customer.name}</Text>
          <Text style={styles.customerCode}>QR {item.hydrometer.code}</Text>
        </View>
        <StatusBadge
          status={item.todayStatus?.status || 'open'}
          mode={isInstallation ? 'installation' : 'reading'}
        />
      </View>
      {isInstallation && <Text style={styles.installationPill}>Instalacao: informar valor inicial, foto e local</Text>}
      {!!item.hydrometer.location_description && <Text style={styles.locationText}>{item.hydrometer.location_description}</Text>}
      <Text style={styles.metaLine}>
        Mostrador: {item.hydrometer.red_digits || 3} digitos vermelhos
        {item.hydrometer.black_digits ? ` - ${item.hydrometer.black_digits} pretos` : ''}
      </Text>
      <View style={styles.rowActionButton}>
        <Text style={styles.rowActionButtonText}>{actionLabel}</Text>
      </View>
    </TouchableOpacity>
  );
}

function TaskCard({ item, onPress }: { item: { customer: Customer; hydrometer: Hydrometer; todayStatus?: ReadingItem; done: boolean }; onPress: () => void }) {
  const isInstallation = !item.hydrometer.last_reading_date;
  return (
    <TouchableOpacity style={styles.taskCard} onPress={onPress} disabled={item.done}>
      <View style={[styles.checkbox, item.done && styles.checkboxDone]}>
        <Text style={styles.checkboxText}>{item.done ? '✓' : ''}</Text>
      </View>
      <View style={{ flex: 1 }}>
        <Text style={styles.customerName}>{item.customer.name}</Text>
        <Text style={styles.metaLine}>{isInstallation ? 'Instalacao pendente' : `QR ${item.hydrometer.code}`}</Text>
      </View>
      <StatusBadge
        status={item.todayStatus?.status || 'open'}
        mode={isInstallation ? 'installation' : 'reading'}
      />
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
        {item.current_value === null || item.current_value === undefined || item.consumption === null || item.consumption === undefined
          ? 'Captura aguardando conferencia no dashboard'
          : `Leitura ${formatMeterReading(item.current_value)} m3 - Consumo ${formatMeterReading(item.consumption)} m3`}
      </Text>
    </View>
  );
}

function ProfileView({
  name,
  email,
  role,
  stats,
  themeMode,
  onThemeChange,
  onLogout,
}: {
  name: string;
  email: string;
  role: string;
  stats: { pending: number; completed: number; total: number; installations: number };
  themeMode: 'light' | 'dark';
  onThemeChange: (mode: 'light' | 'dark') => void;
  onLogout: () => void;
}) {
  return (
    <>
      <View style={styles.profileHero}>
        <View style={styles.avatar}><Text style={styles.avatarText}>{name.slice(0, 1).toUpperCase()}</Text></View>
        <Text style={styles.profileName}>{name}</Text>
        <Text style={styles.heroSubtitle}>{email || role}</Text>
        <View style={styles.summaryRow}>
          <SummaryCard label="Leituras" value={stats.completed} tone="success" />
          <SummaryCard label="Pendentes" value={stats.pending} tone="warning" />
          <SummaryCard label="Instalacoes" value={stats.installations} tone="info" />
        </View>
      </View>
      <View style={styles.customerCard}>
        <Text style={shared.sectionTitle}>Configuracoes</Text>
        <SettingRow label="Notificacoes" value="Ativas no painel" />
        <Text style={styles.settingLabel}>Tema</Text>
        <View style={styles.themeSwitch}>
          <TouchableOpacity
            style={[styles.themeOption, themeMode === 'light' && styles.themeOptionActive]}
            onPress={() => onThemeChange('light')}
          >
            <Text style={[styles.themeOptionText, themeMode === 'light' && styles.themeOptionTextActive]}>Claro</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.themeOption, themeMode === 'dark' && styles.themeOptionActive]}
            onPress={() => onThemeChange('dark')}
          >
            <Text style={[styles.themeOptionText, themeMode === 'dark' && styles.themeOptionTextActive]}>Escuro</Text>
          </TouchableOpacity>
        </View>
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

function StatusBadge({ status, mode = 'reading' }: { status: string; mode?: 'reading' | 'installation' }) {
  let palette = { backgroundColor: colors.warningSoft, color: colors.warning, label: 'Disponivel' };
  if (mode === 'installation') palette = { backgroundColor: colors.accentSoft, color: colors.accent, label: 'Instalar' };
  if (status === 'open') palette = { backgroundColor: colors.warningSoft, color: colors.warning, label: 'Disponivel' };
  if (status === 'pending') palette = { backgroundColor: colors.warningSoft, color: colors.warning, label: 'Revisao' };
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
  const tabs: Array<{ key: ActiveTab; label: string; icon: TabIconName }> = [
    { key: 'home', label: 'Home', icon: 'home' },
    { key: 'tasks', label: 'Tarefas', icon: 'tasks' },
    { key: 'create', label: 'Criar', icon: 'plus' },
    { key: 'history', label: 'Historico', icon: 'history' },
    { key: 'profile', label: 'Perfil', icon: 'profile' },
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
              <TabSvgIcon name={tab.icon} active={selected || isCreate} />
            </View>
            <Text style={[styles.tabLabel, selected && styles.tabLabelActive]}>{tab.label}</Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );
}

type TabIconName = 'home' | 'tasks' | 'plus' | 'history' | 'profile';

function TabSvgIcon({ name, active }: { name: TabIconName; active: boolean }) {
  const stroke = active ? '#fff' : colors.textMuted;
  const common = { stroke, strokeWidth: 2.2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, fill: 'none' };
  return (
    <Svg width={22} height={22} viewBox="0 0 24 24">
      {name === 'home' && <Path {...common} d="M3 11.5 12 4l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1v-8.5Z" />}
      {name === 'tasks' && (
        <>
          <Rect {...common} x="5" y="4" width="14" height="17" rx="2" />
          <Path {...common} d="m9 10 1.7 1.7L15 7.5M9 16h6" />
        </>
      )}
      {name === 'plus' && (
        <>
          <Circle {...common} cx="12" cy="12" r="9" />
          <Line {...common} x1="12" y1="8" x2="12" y2="16" />
          <Line {...common} x1="8" y1="12" x2="16" y2="12" />
        </>
      )}
      {name === 'history' && <Path {...common} d="M4 12a8 8 0 1 0 2.2-5.5M4 5v5h5M12 8v5l3 2" />}
      {name === 'profile' && (
        <>
          <Circle {...common} cx="12" cy="8" r="3.5" />
          <Path {...common} d="M5 21a7 7 0 0 1 14 0" />
        </>
      )}
    </Svg>
  );
}

let styles = createRouteStyles();

function createRouteStyles() {
  return StyleSheet.create({
  screen: { flex: 1, backgroundColor: colors.navy950 },
  loadingWrap: { flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: colors.navy950 },
  loadingText: { marginTop: 14, color: colors.textMuted, fontSize: 13 },
  listContent: { paddingHorizontal: 16, paddingBottom: 104 },
  heroCard: {
    marginTop: 10,
    marginBottom: 16,
    padding: 18,
    borderRadius: 16,
    backgroundColor: colors.navy900,
    borderWidth: 1,
    borderColor: colors.border,
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.06,
    shadowRadius: 14,
    elevation: 2,
    overflow: 'hidden',
  },
  neoLine: { position: 'absolute', top: 0, left: 0, right: 0, height: 3, backgroundColor: colors.accent },
  heroTopRow: { flexDirection: 'row', alignItems: 'center', gap: 10 },
  heroEyebrow: { color: colors.textMuted, fontSize: 11, fontWeight: '800', textTransform: 'uppercase', letterSpacing: 0.8 },
  heroTitle: { color: colors.textPrimary, fontSize: 26, fontWeight: '800', marginTop: 4, letterSpacing: 0 },
  heroSubtitle: { color: colors.textMuted, fontSize: 13, marginTop: 6, lineHeight: 19 },
  logoutPill: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: colors.navy900,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 9,
  },
  logoutText: { color: colors.textPrimary, fontWeight: '800', fontSize: 12 },
  summaryRow: { flexDirection: 'row', gap: 10, marginTop: 16 },
  summaryCard: { flex: 1, borderRadius: 12, padding: 12, minHeight: 72, borderWidth: 1, borderColor: colors.border },
  summaryLabel: { color: colors.textMuted, fontSize: 10, fontWeight: '800', textTransform: 'uppercase', letterSpacing: 0.5 },
  summaryValue: { fontSize: 24, fontWeight: '800', marginTop: 6 },
  progressPanel: { marginTop: 16, padding: 14, borderRadius: 12, backgroundColor: colors.abyss, borderWidth: 1, borderColor: colors.border, flexDirection: 'row', gap: 14, alignItems: 'center' },
  progressRing: { width: 58, height: 58, borderRadius: 29, borderWidth: 4, borderColor: colors.accent, alignItems: 'center', justifyContent: 'center' },
  progressText: { color: colors.textPrimary, fontWeight: '800', fontSize: 14 },
  progressTitle: { color: colors.textPrimary, fontWeight: '800', fontSize: 14 },
  progressSub: { color: colors.textMuted, fontSize: 12, lineHeight: 18, marginTop: 3 },
  searchInput: {
    backgroundColor: colors.navy900,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
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
    backgroundColor: colors.navy900,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    marginBottom: 12,
    shadowColor: '#0F172A',
    shadowOpacity: 0.05,
    shadowRadius: 12,
    elevation: 2,
    overflow: 'hidden',
  },
  customerCardLocked: {
    opacity: 0.78,
  },
  cardTopRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 10 },
  customerName: { color: colors.textPrimary, fontWeight: '800', fontSize: 16 },
  customerCode: { color: colors.accent, fontSize: 12, fontWeight: '700', marginTop: 6 },
  metaLine: { color: colors.textMuted, fontSize: 12, marginTop: 6 },
  installationPill: {
    alignSelf: 'flex-start',
    marginTop: 12,
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 999,
    backgroundColor: colors.accentSoft,
    color: colors.accent,
    fontSize: 11,
    fontWeight: '900',
    textTransform: 'uppercase',
  },
  locationText: { color: colors.textSecondary, fontSize: 13, lineHeight: 19, marginTop: 12 },
  rowActionButton: { marginTop: 14, backgroundColor: colors.accent, borderRadius: 8, paddingVertical: 12, alignItems: 'center' },
  rowActionButtonText: { color: '#fff', fontSize: 14, fontWeight: '800', textTransform: 'uppercase', letterSpacing: 0.5 },
  emptyCard: { backgroundColor: colors.navy800, borderRadius: 14, borderWidth: 1, borderColor: colors.border, padding: 18 },
  emptyTitle: { color: colors.textPrimary, fontSize: 16, fontWeight: '800' },
  emptyText: { color: colors.textSecondary, fontSize: 13, lineHeight: 20, marginTop: 8 },
  segmented: { flexDirection: 'row', backgroundColor: colors.abyss, borderRadius: 12, padding: 4, marginBottom: 14, borderWidth: 1, borderColor: colors.border },
  segment: { flex: 1, paddingVertical: 10, alignItems: 'center', borderRadius: 8 },
  segmentActive: { backgroundColor: colors.accentSoft },
  segmentText: { color: colors.textMuted, fontWeight: '800', fontSize: 12 },
  segmentTextActive: { color: colors.accent },
  taskCard: {
    backgroundColor: colors.navy800,
    borderRadius: 14,
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
    borderRadius: 16,
    backgroundColor: colors.navy900,
    borderWidth: 1,
    borderColor: colors.border,
    alignItems: 'center',
  },
  avatar: { width: 76, height: 76, borderRadius: 16, backgroundColor: colors.accentSoft, alignItems: 'center', justifyContent: 'center', marginBottom: 12 },
  avatarText: { color: colors.accent, fontSize: 34, fontWeight: '800' },
  profileName: { color: colors.textPrimary, fontSize: 24, fontWeight: '800' },
  settingRow: { paddingVertical: 13, borderBottomWidth: 1, borderBottomColor: colors.border, flexDirection: 'row', justifyContent: 'space-between', gap: 12 },
  settingLabel: { color: colors.textPrimary, fontWeight: '800' },
  settingValue: { color: colors.textMuted, fontSize: 12 },
  themeSwitch: { flexDirection: 'row', gap: 8, marginTop: 10 },
  themeOption: { flex: 1, borderWidth: 1, borderColor: colors.border, backgroundColor: colors.abyss, borderRadius: 10, paddingVertical: 11, alignItems: 'center' },
  themeOptionActive: { borderColor: colors.accent, backgroundColor: colors.accentSoft },
  themeOptionText: { color: colors.textMuted, fontWeight: '800', fontSize: 12 },
  themeOptionTextActive: { color: colors.accent },
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
  tabIcon: { width: 34, height: 34, borderRadius: 10, alignItems: 'center', justifyContent: 'center' },
  tabIconActive: { backgroundColor: colors.accentSoft },
  createIcon: { backgroundColor: colors.accent, width: 52, height: 52, borderRadius: 16, marginTop: -16, borderWidth: 4, borderColor: '#FFFFFF' },
  activeBeam: { position: 'absolute', bottom: -8, width: 22, height: 3, borderRadius: 2, backgroundColor: colors.accent },
  tabIconText: { color: colors.textMuted, fontWeight: '900', fontSize: 14 },
  tabIconTextActive: { color: '#fff' },
  tabLabel: { color: colors.textMuted, fontSize: 10, fontWeight: '800', marginTop: 3 },
  tabLabelActive: { color: colors.textPrimary },
  modalBackdrop: { flex: 1, backgroundColor: 'rgba(15,23,42,0.38)', justifyContent: 'flex-end', padding: 16 },
  modalCard: { backgroundColor: colors.navy900, borderRadius: 16, borderWidth: 1, borderColor: colors.border, padding: 18, marginBottom: 70 },
  modalTitle: { color: colors.textPrimary, fontSize: 20, fontWeight: '800' },
  backText: { color: colors.accent, fontWeight: '800' },
  actionGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 12, marginTop: 18 },
  actionTile: { width: '48%', backgroundColor: colors.abyss, borderRadius: 12, borderWidth: 1, borderColor: colors.border, padding: 14, minHeight: 92 },
  actionTitle: { color: colors.textPrimary, fontWeight: '800', fontSize: 15 },
  actionSubtitle: { color: colors.textMuted, fontSize: 12, lineHeight: 18, marginTop: 8 },
  floatingDevButton: {
    position: 'absolute',
    right: 18,
    bottom: 96,
    width: 54,
    height: 54,
    borderRadius: 27,
    backgroundColor: colors.cyan,
    justifyContent: 'center',
    alignItems: 'center',
    elevation: 6,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.28,
    shadowRadius: 5,
  },
  });
}
