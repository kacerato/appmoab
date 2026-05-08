import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, FlatList, RefreshControl, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation } from '@react-navigation/native';
import { api } from '../lib/api';
import { useAuth } from '../lib/auth';
import { useFeedback } from '../lib/feedback';
import { colors, shared } from '../styles/theme';

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

export default function DayHistoryScreen() {
  const navigation = useNavigation<any>();
  const { user } = useAuth();
  const { showToast } = useFeedback();
  const [readings, setReadings] = useState<ReadingItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.get<{ items: ReadingItem[] }>('/readings?per_page=200');
      const todayKey = new Date().toISOString().slice(0, 10);
      setReadings(
        (res.items || []).filter(item => item.collaborator_id === user?.id && item.captured_at.slice(0, 10) === todayKey),
      );
    } catch (error) {
      console.error(error);
      showToast(
        'Falha ao carregar historico',
        error instanceof Error ? error.message : 'Nao foi possivel carregar o historico do dia.',
        'error',
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [showToast, user?.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = useMemo(() => ({
    approved: readings.filter(item => item.status === 'approved').length,
    pending: readings.filter(item => item.status === 'pending').length,
    rejected: readings.filter(item => item.status === 'rejected').length,
  }), [readings]);

  return (
    <SafeAreaView style={shared.safeArea} edges={['top', 'left', 'right']}>
      <View style={styles.screen}>
        {loading ? (
          <View style={styles.loadingWrap}>
            <ActivityIndicator size="large" color={colors.accent} />
            <Text style={styles.loadingText}>Carregando historico do dia...</Text>
          </View>
        ) : (
          <FlatList
            data={readings}
            keyExtractor={item => item.id}
            refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); void load(); }} tintColor={colors.accent} />}
            contentContainerStyle={styles.listContent}
            ListHeaderComponent={
              <>
                <View style={styles.heroCard}>
                  <TouchableOpacity onPress={() => navigation.goBack()}>
                    <Text style={styles.backLink}>Voltar para rota</Text>
                  </TouchableOpacity>
                  <Text style={styles.title}>Historico do dia</Text>
                  <Text style={styles.subtitle}>Tudo que voce ja capturou hoje fica consolidado aqui.</Text>

                  <View style={styles.summaryRow}>
                    <MetricCard label="Aprovadas" value={counts.approved} tone="success" />
                    <MetricCard label="Pendentes" value={counts.pending} tone="warning" />
                    <MetricCard label="Rejeitadas" value={counts.rejected} tone="danger" />
                  </View>
                </View>

                <View style={styles.sectionHeader}>
                  <Text style={styles.sectionTitle}>Leituras registradas</Text>
                  <Text style={styles.sectionCaption}>{readings.length} item(ns) hoje</Text>
                </View>
              </>
            }
            renderItem={({ item }) => (
              <View style={styles.readingCard}>
                <View style={styles.readingTopRow}>
                  <View>
                    <Text style={styles.customerName}>{item.customer_name || 'Cliente sem nome'}</Text>
                    <Text style={styles.metaLine}>
                      {item.hydrometer_code || 'Sem codigo'} • {new Date(item.captured_at).toLocaleTimeString('pt-BR')}
                    </Text>
                  </View>
                  <StatusBadge status={item.status} />
                </View>

                <View style={styles.metricsRow}>
                  <MetricMini label="Leitura" value={`${item.current_value.toFixed(2)} m³`} />
                  <MetricMini label="Consumo" value={`${item.consumption.toFixed(2)} m³`} />
                </View>
              </View>
            )}
            ListEmptyComponent={
              <View style={shared.card}>
                <Text style={styles.emptyTitle}>Nenhuma leitura hoje</Text>
                <Text style={styles.emptyText}>
                  Assim que voce concluir uma captura na rota, ela aparece aqui com status e horario.
                </Text>
              </View>
            }
          />
        )}
      </View>
    </SafeAreaView>
  );
}

function MetricCard({ label, value, tone }: { label: string; value: number; tone: 'success' | 'warning' | 'danger' }) {
  const palette = {
    success: { bg: colors.successSoft, text: colors.success },
    warning: { bg: colors.warningSoft, text: colors.warning },
    danger: { bg: colors.dangerSoft, text: colors.danger },
  }[tone];

  return (
    <View style={[styles.metricCard, { backgroundColor: palette.bg }]}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={[styles.metricValue, { color: palette.text }]}>{value}</Text>
    </View>
  );
}

function MetricMini({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.metricMini}>
      <Text style={styles.metricMiniLabel}>{label}</Text>
      <Text style={styles.metricMiniValue}>{value}</Text>
    </View>
  );
}

function StatusBadge({ status }: { status: string }) {
  let palette = { backgroundColor: colors.warningSoft, color: colors.warning, label: 'Pendente' };
  if (status === 'approved') palette = { backgroundColor: colors.successSoft, color: colors.success, label: 'Aprovada' };
  if (status === 'rejected') palette = { backgroundColor: colors.dangerSoft, color: colors.danger, label: 'Rejeitada' };

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
  backLink: {
    color: colors.cyan,
    fontSize: 12,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  title: {
    color: colors.textPrimary,
    fontSize: 27,
    fontWeight: '900',
    marginTop: 10,
  },
  subtitle: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 20,
    marginTop: 8,
  },
  summaryRow: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 18,
  },
  metricCard: {
    flex: 1,
    borderRadius: 16,
    padding: 14,
  },
  metricLabel: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
    marginBottom: 8,
  },
  metricValue: {
    fontSize: 24,
    fontWeight: '900',
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
  readingCard: {
    backgroundColor: colors.navy800,
    borderRadius: 22,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 18,
    marginBottom: 14,
  },
  readingTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 12,
  },
  customerName: {
    color: colors.textPrimary,
    fontSize: 16,
    fontWeight: '900',
  },
  metaLine: {
    color: colors.textMuted,
    fontSize: 12,
    marginTop: 6,
  },
  metricsRow: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 16,
  },
  metricMini: {
    flex: 1,
    backgroundColor: colors.navy900,
    borderRadius: 16,
    padding: 14,
    borderWidth: 1,
    borderColor: colors.border,
  },
  metricMiniLabel: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: '800',
    textTransform: 'uppercase',
    marginBottom: 6,
  },
  metricMiniValue: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: '800',
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
