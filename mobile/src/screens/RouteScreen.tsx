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
  status: string;
  hydrometers: Hydrometer[];
}

interface ReadingItem {
  id: string;
  hydrometer_id: string;
  collaborator_id: string;
  current_value: number;
  consumption: number;
  captured_at: string;
  status: string;
  customer_name: string | null;
  hydrometer_code: string | null;
}

function normalizeMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Nao foi possivel atualizar sua rota.';
}

export default function RouteScreen() {
  const navigation = useNavigation<any>();
  const { user, logout } = useAuth();
  const { showToast } = useFeedback();
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [todayReadings, setTodayReadings] = useState<ReadingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [customersRes, readingsRes] = await Promise.all([
        api.get<{ items: Customer[] }>('/customers?has_hydrometer=true&status=active&per_page=100'),
        api.get<{ items: ReadingItem[] }>('/readings?per_page=200'),
      ]);

      const todayKey = new Date().toISOString().slice(0, 10);
      const ownToday = readingsRes.items.filter(
        item => item.collaborator_id === user?.id && item.captured_at.slice(0, 10) === todayKey,
      );

      setCustomers((customersRes.items || []).filter(customer => customer.hydrometers?.length));
      setTodayReadings(ownToday);
    } catch (error) {
      console.error(error);
      showToast('Falha ao carregar rota', normalizeMessage(error), 'error');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [showToast, user?.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const onRefresh = () => {
    setRefreshing(true);
    void load();
  };

  const statusByHydrometer = useMemo(() => {
    const map = new Map<string, ReadingItem>();
    for (const reading of todayReadings) {
      map.set(reading.hydrometer_id, reading);
    }
    return map;
  }, [todayReadings]);

  const routeItems = useMemo(() => {
    return customers
      .filter(customer => customer.hydrometers?.[0])
      .map(customer => {
        const hydrometer = customer.hydrometers[0];
        const todayStatus = statusByHydrometer.get(hydrometer.id);
        return { customer, hydrometer, todayStatus };
      });
  }, [customers, statusByHydrometer]);

  const stats = useMemo(() => {
    const total = routeItems.length;
    const done = routeItems.filter(item => item.todayStatus && item.todayStatus.status !== 'rejected').length;
    const rejected = routeItems.filter(item => item.todayStatus?.status === 'rejected').length;
    return { total, done, pending: Math.max(0, total - done), rejected };
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

  if (loading) {
    return (
      <SafeAreaView style={[shared.container, styles.centered]}>
        <ActivityIndicator size="large" color={colors.accent} />
        <Text style={styles.loadingText}>Montando sua rota de hoje...</Text>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={shared.safeArea} edges={['top', 'left', 'right']}>
      <View style={styles.screen}>
        <FlatList
          data={routeItems}
          keyExtractor={item => item.customer.id}
          refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}
          contentContainerStyle={styles.listContent}
          ListHeaderComponent={
            <>
              <View style={styles.heroCard}>
                <View style={styles.heroTopRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.heroEyebrow}>Operacao de campo</Text>
                    <Text style={styles.heroTitle}>Rota do dia</Text>
                    <Text style={styles.heroSubtitle}>
                      {user?.name || 'Colaborador'} • capture primeiro o codigo e depois a medicao.
                    </Text>
                  </View>
                  <TouchableOpacity style={styles.logoutPill} onPress={logout}>
                    <Text style={styles.logoutText}>Sair</Text>
                  </TouchableOpacity>
                </View>

                <View style={styles.summaryRow}>
                  <SummaryCard label="Pendentes" value={stats.pending} tone="warning" />
                  <SummaryCard label="Concluidos" value={stats.done} tone="success" />
                  <SummaryCard label="Rejeitados" value={stats.rejected} tone="danger" />
                </View>

                <View style={styles.flowCard}>
                  <Text style={shared.sectionTitle}>Fluxo da leitura</Text>
                  <Text style={styles.flowText}>
                    1. Escanear codigo. 2. Validar cliente e local. 3. Fotografar mostrador. 4. Revisar. 5. Enviar para aprovacao.
                  </Text>
                  <TouchableOpacity
                    style={[shared.btnSecondary, styles.historyButton]}
                    onPress={() => navigation.navigate('DayHistory')}
                  >
                    <Text style={shared.btnSecondaryText}>Abrir historico do dia</Text>
                  </TouchableOpacity>
                </View>
              </View>

              <View style={styles.sectionHeader}>
                <Text style={styles.sectionTitle}>Pontos da rota</Text>
                <Text style={styles.sectionCaption}>{stats.total} hidrômetro(s) ativos</Text>
              </View>
            </>
          }
          renderItem={({ item, index }) => {
            const status = item.todayStatus?.status || 'pending';
            return (
              <View style={styles.customerCard}>
                <View style={styles.cardTopRow}>
                  <View style={styles.indexPill}>
                    <Text style={styles.indexText}>{String(index + 1).padStart(2, '0')}</Text>
                  </View>
                  <StatusBadge status={status} />
                </View>

                <Text style={styles.customerName}>{item.customer.name}</Text>
                <Text style={styles.customerAddr}>{item.customer.address}, {item.customer.city}</Text>

                <View style={styles.metaGrid}>
                  <MetaBlock label="Codigo" value={item.hydrometer.code} />
                  <MetaBlock label="Ultima leitura" value={`${item.hydrometer.last_reading_value.toFixed(2)} m³`} />
                </View>

                <View style={styles.locationBox}>
                  <Text style={styles.locationLabel}>Referencia do local</Text>
                  <Text style={styles.locationText}>
                    {item.hydrometer.location_description || 'Sem observacao adicional no cadastro.'}
                  </Text>
                </View>

                <TouchableOpacity style={styles.captureButton} onPress={() => startCapture(item)}>
                  <Text style={styles.captureButtonText}>Abrir camera e escanear codigo</Text>
                </TouchableOpacity>
              </View>
            );
          }}
          ListEmptyComponent={
            <View style={shared.card}>
              <Text style={styles.emptyTitle}>Nenhuma rota disponivel agora</Text>
              <Text style={styles.emptyText}>
                Verifique se existem clientes ativos com hidrômetro cadastrado e se sua API mobile está apontando para o backend certo.
              </Text>
            </View>
          }
        />
      </View>
    </SafeAreaView>
  );
}

function SummaryCard({ label, value, tone }: { label: string; value: number; tone: 'warning' | 'success' | 'danger' }) {
  const palette = {
    warning: { bg: colors.warningSoft, text: colors.warning },
    success: { bg: colors.successSoft, text: colors.success },
    danger: { bg: colors.dangerSoft, text: colors.danger },
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
  if (status === 'approved') {
    palette = { backgroundColor: colors.successSoft, color: colors.success, label: 'Aprovado' };
  } else if (status === 'rejected') {
    palette = { backgroundColor: colors.dangerSoft, color: colors.danger, label: 'Rejeitado' };
  }

  return (
    <View style={[shared.badge, { backgroundColor: palette.backgroundColor }]}>
      <Text style={[shared.badgeText, { color: palette.color }]}>{palette.label}</Text>
    </View>
  );
}

function MetaBlock({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metaBlock}>
      <Text style={styles.metaLabel}>{label}</Text>
      <Text style={styles.metaValue}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: colors.navy950,
  },
  centered: {
    justifyContent: 'center',
    alignItems: 'center',
  },
  loadingText: {
    marginTop: 14,
    color: colors.textMuted,
    fontSize: 13,
  },
  listContent: {
    paddingHorizontal: 18,
    paddingBottom: 32,
  },
  heroCard: {
    marginTop: 10,
    marginBottom: 18,
    padding: 20,
    borderRadius: 28,
    backgroundColor: colors.sidebarNavy,
    borderWidth: 1,
    borderColor: colors.border,
  },
  heroTopRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    gap: 12,
  },
  heroEyebrow: {
    color: colors.cyan,
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 0.9,
  },
  heroTitle: {
    color: colors.textPrimary,
    fontSize: 28,
    fontWeight: '900',
    marginTop: 6,
  },
  heroSubtitle: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 20,
    marginTop: 8,
  },
  logoutPill: {
    borderWidth: 1,
    borderColor: colors.borderHover,
    backgroundColor: 'rgba(255,255,255,0.05)',
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  logoutText: {
    color: colors.textPrimary,
    fontWeight: '800',
    fontSize: 12,
  },
  summaryRow: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 18,
    marginBottom: 18,
  },
  summaryCard: {
    flex: 1,
    borderRadius: 16,
    padding: 14,
    minHeight: 84,
    justifyContent: 'space-between',
  },
  summaryLabel: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  summaryValue: {
    fontSize: 26,
    fontWeight: '900',
  },
  flowCard: {
    borderRadius: 20,
    padding: 18,
    backgroundColor: 'rgba(7, 17, 31, 0.54)',
    borderWidth: 1,
    borderColor: colors.border,
  },
  flowText: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 20,
  },
  historyButton: {
    marginTop: 14,
  },
  sectionHeader: {
    marginBottom: 12,
  },
  sectionTitle: {
    color: colors.textPrimary,
    fontSize: 18,
    fontWeight: '800',
  },
  sectionCaption: {
    color: colors.textMuted,
    fontSize: 12,
    marginTop: 4,
  },
  customerCard: {
    backgroundColor: colors.navy800,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 18,
    marginBottom: 14,
  },
  cardTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 12,
  },
  indexPill: {
    backgroundColor: colors.accentSoft,
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 999,
  },
  indexText: {
    color: colors.accent,
    fontWeight: '800',
    fontSize: 12,
  },
  customerName: {
    color: colors.textPrimary,
    fontWeight: '900',
    fontSize: 17,
  },
  customerAddr: {
    color: colors.textMuted,
    fontSize: 13,
    marginTop: 6,
    lineHeight: 19,
  },
  metaGrid: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 16,
  },
  metaBlock: {
    flex: 1,
    borderRadius: 16,
    padding: 14,
    backgroundColor: colors.navy900,
    borderWidth: 1,
    borderColor: colors.border,
  },
  metaLabel: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
    marginBottom: 6,
  },
  metaValue: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: '800',
  },
  locationBox: {
    marginTop: 14,
    borderRadius: 16,
    padding: 14,
    backgroundColor: 'rgba(83, 211, 247, 0.08)',
  },
  locationLabel: {
    color: colors.cyan,
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
    marginBottom: 6,
  },
  locationText: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 19,
  },
  captureButton: {
    marginTop: 16,
    backgroundColor: colors.accent,
    borderRadius: 16,
    paddingVertical: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  captureButtonText: {
    color: '#fff',
    fontSize: 14,
    fontWeight: '900',
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
});
