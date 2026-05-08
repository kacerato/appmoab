import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  RefreshControl,
  StyleSheet,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { useAuth } from '../lib/auth';
import { api } from '../lib/api';
import { useFeedback } from '../lib/feedback';
import { colors, shared } from '../styles/theme';

interface Hydrometer {
  id: string;
  code: string;
  last_reading_value: number;
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
  hydrometer_id: string;
  collaborator_id: string;
  captured_at: string;
  status: string;
}

function getMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

export default function RouteScreen() {
  const navigation = useNavigation<any>();
  const { user, logout } = useAuth();
  const { showToast } = useFeedback();
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [todayReadings, setTodayReadings] = useState<ReadingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const openManualScan = useCallback(() => {
    navigation.navigate('Camera', { stage: 'code' });
  }, [navigation]);

  const load = useCallback(async () => {
    setLoading(prev => (refreshing ? prev : true));

    const customersRequest = api.get<{ items: Customer[] }>('/customers?has_hydrometer=true&status=active&per_page=100');
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

    setLoading(false);
    setRefreshing(false);
  }, [refreshing, showToast, user?.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const routeItems = useMemo(() => {
    const byHydrometer = new Map<string, ReadingItem>();
    for (const reading of todayReadings) byHydrometer.set(reading.hydrometer_id, reading);

    return customers.map(customer => {
      const hydrometer = customer.hydrometers[0];
      return {
        customer,
        hydrometer,
        todayStatus: hydrometer ? byHydrometer.get(hydrometer.id) : undefined,
      };
    }).filter(item => item.hydrometer);
  }, [customers, todayReadings]);

  const stats = useMemo(() => {
    const total = routeItems.length;
    const completed = routeItems.filter(item => item.todayStatus && item.todayStatus.status !== 'rejected').length;
    return {
      total,
      pending: Math.max(total - completed, 0),
      completed,
    };
  }, [routeItems]);

  const startCapture = useCallback((item: { customer: Customer; hydrometer: Hydrometer }) => {
    navigation.navigate('Camera', {
      stage: 'code',
      expectedCustomerId: item.customer.id,
      expectedCustomerName: item.customer.name,
      expectedHydrometerId: item.hydrometer.id,
      expectedHydrometerCode: item.hydrometer.code,
      lastReading: item.hydrometer.last_reading_value || 0,
      locationDescription: item.hydrometer.location_description || '',
    });
  }, [navigation]);

  return (
    <SafeAreaView style={shared.safeArea} edges={['top', 'left', 'right']}>
      <View style={styles.screen}>
        {loading ? (
          <View style={styles.loadingWrap}>
            <ActivityIndicator size="large" color={colors.accent} />
            <Text style={styles.loadingText}>Carregando rota...</Text>
          </View>
        ) : (
          <>
            <FlatList
              data={routeItems}
              keyExtractor={item => item.customer.id}
              refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); void load(); }} tintColor={colors.accent} />}
              contentContainerStyle={styles.listContent}
              ListHeaderComponent={
                <>
                  <View style={styles.heroCard}>
                    <View style={styles.heroTopRow}>
                      <View style={{ flex: 1 }}>
                        <Text style={styles.heroEyebrow}>Operacao de campo</Text>
                        <Text style={styles.heroTitle}>Rota do dia</Text>
                        <Text style={styles.heroSubtitle}>{user?.name || 'Colaborador'}</Text>
                      </View>
                      <TouchableOpacity style={styles.logoutPill} onPress={logout}>
                        <Text style={styles.logoutText}>Sair</Text>
                      </TouchableOpacity>
                    </View>

                    <View style={styles.summaryRow}>
                      <SummaryCard label="Pendentes" value={stats.pending} tone="warning" />
                      <SummaryCard label="Concluidas" value={stats.completed} tone="success" />
                      <SummaryCard label="Rota" value={stats.total} tone="info" />
                    </View>

                    <TouchableOpacity style={styles.historyButton} onPress={() => navigation.navigate('DayHistory')}>
                      <Text style={styles.historyButtonText}>Ver historico do dia</Text>
                    </TouchableOpacity>
                  </View>

                  <View style={styles.sectionHeader}>
                    <Text style={styles.sectionTitle}>Pontos da rota</Text>
                  </View>
                </>
              }
              renderItem={({ item }) => (
                <View style={styles.customerCard}>
                  <View style={styles.cardTopRow}>
                    <View style={{ flex: 1 }}>
                      <Text style={styles.customerName}>{item.customer.name}</Text>
                      <Text style={styles.customerCode}>Codigo {item.hydrometer.code}</Text>
                    </View>
                    <StatusBadge status={item.todayStatus?.status || 'pending'} />
                  </View>

                  {!!item.hydrometer.location_description && (
                    <Text style={styles.locationText}>{item.hydrometer.location_description}</Text>
                  )}

                  <TouchableOpacity style={styles.rowActionButton} onPress={() => startCapture(item)}>
                    <Text style={styles.rowActionButtonText}>Escanear este hidrometro</Text>
                  </TouchableOpacity>
                </View>
              )}
              ListEmptyComponent={
                <View style={styles.emptyCard}>
                  <Text style={styles.emptyTitle}>Nenhum ponto carregado</Text>
                  <Text style={styles.emptyText}>
                    Se os hidrômetros existem no painel, toque em atualizar ou use o scan manual abaixo.
                  </Text>
                </View>
              }
            />

            <View style={styles.floatingActionWrap}>
              <TouchableOpacity style={styles.floatingAction} onPress={openManualScan}>
                <Text style={styles.floatingActionText}>Abrir camera</Text>
              </TouchableOpacity>
            </View>
          </>
        )}
      </View>
    </SafeAreaView>
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

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.navy950,
  },
  loadingWrap: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    marginTop: 14,
    color: colors.textMuted,
    fontSize: 13,
  },
  listContent: {
    paddingHorizontal: 16,
    paddingBottom: 120,
  },
  heroCard: {
    marginTop: 10,
    marginBottom: 16,
    padding: 18,
    borderRadius: 24,
    backgroundColor: colors.sidebarNavy,
    borderWidth: 1,
    borderColor: colors.border,
  },
  heroTopRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
  },
  heroEyebrow: {
    color: colors.cyan,
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  heroTitle: {
    color: colors.textPrimary,
    fontSize: 30,
    fontWeight: '900',
    marginTop: 4,
  },
  heroSubtitle: {
    color: colors.textMuted,
    fontSize: 13,
    marginTop: 6,
  },
  logoutPill: {
    borderWidth: 1,
    borderColor: colors.border,
    backgroundColor: 'rgba(255,255,255,0.04)',
    borderRadius: 999,
    paddingHorizontal: 12,
    paddingVertical: 9,
  },
  logoutText: {
    color: colors.textPrimary,
    fontWeight: '800',
    fontSize: 12,
  },
  summaryRow: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 16,
  },
  summaryCard: {
    flex: 1,
    borderRadius: 16,
    padding: 12,
  },
  summaryLabel: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  summaryValue: {
    fontSize: 24,
    fontWeight: '900',
    marginTop: 6,
  },
  historyButton: {
    marginTop: 14,
    backgroundColor: colors.navy700,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 16,
    paddingVertical: 14,
    alignItems: 'center',
  },
  historyButtonText: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: '800',
  },
  sectionHeader: {
    marginBottom: 10,
  },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 19,
    fontWeight: '800',
  },
  customerCard: {
    backgroundColor: colors.navy800,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    marginBottom: 12,
  },
  cardTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 10,
  },
  customerName: {
    color: colors.textPrimary,
    fontWeight: '900',
    fontSize: 17,
  },
  customerCode: {
    color: colors.cyan,
    fontSize: 12,
    fontWeight: '700',
    marginTop: 6,
  },
  locationText: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 19,
    marginTop: 12,
  },
  rowActionButton: {
    marginTop: 14,
    backgroundColor: colors.accentSoft,
    borderRadius: 14,
    paddingVertical: 13,
    alignItems: 'center',
  },
  rowActionButtonText: {
    color: colors.accent,
    fontSize: 14,
    fontWeight: '900',
  },
  emptyCard: {
    backgroundColor: colors.navy800,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 18,
  },
  emptyTitle: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: '800',
  },
  emptyText: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 20,
    marginTop: 8,
  },
  floatingActionWrap: {
    position: 'absolute',
    left: 16,
    right: 16,
    bottom: 18,
  },
  floatingAction: {
    backgroundColor: colors.accent,
    borderRadius: 18,
    paddingVertical: 18,
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.22,
    shadowRadius: 18,
    elevation: 10,
  },
  floatingActionText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '900',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
  },
});
