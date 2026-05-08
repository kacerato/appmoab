import React, { useEffect, useMemo, useState, useCallback } from 'react';
import {
  View,
  Text,
  FlatList,
  TouchableOpacity,
  StyleSheet,
  RefreshControl,
  ActivityIndicator,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useAuth } from '../lib/auth';
import { api } from '../lib/api';
import { useFeedback } from '../lib/feedback';
import { colors, shared } from '../styles/theme';

interface Customer {
  id: string;
  name: string;
  address: string;
  city: string;
  status: string;
  hydrometers: { id: string; code: string; last_reading_value: number; location_description?: string }[];
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
      const ownToday = readingsRes.items.filter(item =>
        item.collaborator_id === user?.id &&
        item.captured_at.slice(0, 10) === todayKey
      );

      setCustomers(customersRes.items);
      setTodayReadings(ownToday);
    } catch (error) {
      console.error(error);
      showToast('Falha ao carregar rota', error instanceof Error ? error.message : 'Não foi possível atualizar sua rota.', 'error');
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
        return {
          customer,
          hydrometer,
          todayStatus,
        };
      });
  }, [customers, statusByHydrometer]);

  const stats = useMemo(() => {
    const total = routeItems.length;
    const done = routeItems.filter(item => item.todayStatus && item.todayStatus.status !== 'rejected').length;
    const pending = total - done;
    const rejected = routeItems.filter(item => item.todayStatus?.status === 'rejected').length;
    return { total, done, pending, rejected };
  }, [routeItems]);

  if (loading) {
    return (
      <View style={[shared.container, { justifyContent: 'center', alignItems: 'center' }]}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
  }

  return (
    <View style={shared.container}>
      <View style={shared.headerBar}>
        <View>
          <Text style={shared.title}>Rota do dia</Text>
          <Text style={shared.subtitle}>{user?.name} · foco em hidrômetros pendentes</Text>
        </View>
        <TouchableOpacity onPress={logout}>
          <Text style={{ color: colors.danger, fontWeight: '700', fontSize: 13 }}>Sair</Text>
        </TouchableOpacity>
      </View>

      <FlatList
        data={routeItems}
        keyExtractor={item => item.customer.id}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}
        contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
        ListHeaderComponent={
          <>
            <View style={styles.summaryRow}>
              <SummaryCard label="Pendentes" value={stats.pending} tone="warning" />
              <SummaryCard label="Concluídos" value={stats.done} tone="success" />
              <SummaryCard label="Rejeitados" value={stats.rejected} tone="danger" />
            </View>

            <View style={shared.card}>
              <Text style={shared.sectionTitle}>Checklist operacional</Text>
              <Text style={styles.helperText}>
                1. Escaneie primeiro o código do hidrômetro. 2. Confirme a associação com cliente e local. 3. Capture a leitura. 4. Revise os dados antes de enviar.
              </Text>
              <TouchableOpacity
                style={[shared.btnSecondary, { marginTop: 14 }]}
                onPress={() => navigation.navigate('DayHistory')}
              >
                <Text style={shared.btnSecondaryText}>Ver histórico do dia</Text>
              </TouchableOpacity>
            </View>
          </>
        }
        renderItem={({ item }) => {
          const status = item.todayStatus?.status || 'pending';
          return (
            <TouchableOpacity
              style={styles.customerCard}
              onPress={() => navigation.navigate('Camera', {
                stage: 'code',
                expectedCustomerId: item.customer.id,
                expectedCustomerName: item.customer.name,
                expectedHydrometerId: item.hydrometer.id,
                expectedHydrometerCode: item.hydrometer.code,
                lastReading: item.hydrometer.last_reading_value || 0,
                locationDescription: item.hydrometer.location_description || '',
              })}
            >
              <View style={styles.customerRow}>
                <View style={styles.avatar}>
                  <Text style={styles.avatarText}>{item.customer.name.charAt(0)}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <Text style={styles.customerName}>{item.customer.name}</Text>
                  <Text style={styles.customerAddr}>{item.customer.address}, {item.customer.city}</Text>
                  <Text style={styles.meterInfo}>
                    {item.hydrometer.code} · última leitura {item.hydrometer.last_reading_value.toFixed(2)} m³
                  </Text>
                </View>
                <StatusBadge status={status} />
              </View>
            </TouchableOpacity>
          );
        }}
        ListEmptyComponent={
          <View style={{ alignItems: 'center', paddingTop: 60 }}>
            <Text style={{ color: colors.textMuted, fontSize: 14 }}>Nenhum cliente pendente na rota</Text>
          </View>
        }
      />
    </View>
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

const styles = StyleSheet.create({
  summaryRow: {
    flexDirection: 'row',
    gap: 10,
    marginBottom: 14,
  },
  summaryCard: {
    flex: 1,
    borderRadius: 16,
    padding: 14,
  },
  summaryLabel: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: '700',
    textTransform: 'uppercase',
    marginBottom: 6,
  },
  summaryValue: {
    fontSize: 24,
    fontWeight: '800',
  },
  helperText: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 20,
  },
  customerCard: {
    backgroundColor: colors.navy800,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 16,
    marginBottom: 10,
  },
  customerRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
  },
  avatar: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: colors.accentSoft,
    alignItems: 'center',
    justifyContent: 'center',
  },
  avatarText: {
    color: colors.accent,
    fontWeight: '800',
    fontSize: 16,
  },
  customerName: {
    color: colors.textPrimary,
    fontWeight: '800',
    fontSize: 15,
  },
  customerAddr: {
    color: colors.textMuted,
    fontSize: 12,
    marginTop: 2,
  },
  meterInfo: {
    color: colors.cyan,
    fontSize: 12,
    marginTop: 5,
    fontWeight: '600',
  },
});
