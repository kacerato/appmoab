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

function getMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
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
      const res = await api.get<{ items: ReadingItem[] }>('/readings?per_page=100');
      const todayKey = new Date().toISOString().slice(0, 10);
      setReadings(
        (res.items || []).filter(item => item.collaborator_id === user?.id && item.captured_at.slice(0, 10) === todayKey),
      );
    } catch (error) {
      showToast('Falha ao carregar historico', getMessage(error, 'Nao foi possivel carregar o historico do dia.'), 'error');
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
  }), [readings]);

  return (
    <SafeAreaView style={shared.safeArea} edges={['top', 'left', 'right']}>
      <View style={styles.screen}>
        {loading ? (
          <View style={styles.loadingWrap}>
            <ActivityIndicator size="large" color={colors.accent} />
            <Text style={styles.loadingText}>Carregando historico...</Text>
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
                  <Text style={styles.subtitle}>Resumo simples das leituras registradas hoje.</Text>

                  <View style={styles.summaryRow}>
                    <MetricCard label="Aprovadas" value={counts.approved} tone="success" />
                    <MetricCard label="Pendentes" value={counts.pending} tone="warning" />
                    <MetricCard label="Total" value={readings.length} tone="info" />
                  </View>
                </View>
              </>
            }
            renderItem={({ item }) => (
              <View style={styles.readingCard}>
                <View style={styles.readingTopRow}>
                  <View style={{ flex: 1 }}>
                    <Text style={styles.customerName}>{item.customer_name || 'Cliente sem nome'}</Text>
                    <Text style={styles.metaLine}>
                      {item.hydrometer_code || 'Sem codigo'} • {new Date(item.captured_at).toLocaleTimeString('pt-BR')}
                    </Text>
                  </View>
                  <StatusBadge status={item.status} />
                </View>

                <Text style={styles.valueLine}>
                  Leitura {item.current_value.toFixed(2)} m³ • Consumo {item.consumption.toFixed(2)} m³
                </Text>
              </View>
            )}
            ListEmptyComponent={
              <View style={styles.emptyCard}>
                <Text style={styles.emptyTitle}>Nenhuma leitura hoje</Text>
                <Text style={styles.emptyText}>Quando voce concluir uma captura, ela aparece aqui.</Text>
              </View>
            }
          />
        )}
      </View>
    </SafeAreaView>
  );
}

function MetricCard({ label, value, tone }: { label: string; value: number; tone: 'success' | 'warning' | 'info' }) {
  const palette = {
    success: { bg: colors.successSoft, text: colors.success },
    warning: { bg: colors.warningSoft, text: colors.warning },
    info: { bg: colors.accentSoft, text: colors.accent },
  }[tone];

  return (
    <View style={[styles.metricCard, { backgroundColor: palette.bg }]}>
      <Text style={styles.metricLabel}>{label}</Text>
      <Text style={[styles.metricValue, { color: palette.text }]}>{value}</Text>
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
  },
  listContent: {
    paddingHorizontal: 16,
    paddingBottom: 32,
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
  backLink: {
    color: colors.cyan,
    fontSize: 12,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
  },
  title: {
    color: colors.textPrimary,
    fontSize: 28,
    fontWeight: '900',
    marginTop: 10,
  },
  subtitle: {
    color: colors.textSecondary,
    fontSize: 13,
    marginTop: 8,
  },
  summaryRow: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 16,
  },
  metricCard: {
    flex: 1,
    borderRadius: 16,
    padding: 12,
  },
  metricLabel: {
    color: colors.textMuted,
    fontSize: 10,
    fontWeight: '800',
    textTransform: 'uppercase',
  },
  metricValue: {
    fontSize: 24,
    fontWeight: '900',
    marginTop: 6,
  },
  readingCard: {
    backgroundColor: colors.navy800,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    marginBottom: 12,
  },
  readingTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 10,
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
  valueLine: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 19,
    marginTop: 12,
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
});
