import React, { useEffect, useState, useCallback } from 'react';
import {
  View, Text, FlatList, TouchableOpacity, StyleSheet,
  RefreshControl, ActivityIndicator,
} from 'react-native';
import { useNavigation } from '@react-navigation/native';
import { useAuth } from '../lib/auth';
import { api } from '../lib/api';
import { colors, shared } from '../styles/theme';

interface Customer {
  id: string;
  name: string;
  address: string;
  city: string;
  has_hydrometer: boolean;
  status: string;
  hydrometers: { id: string; code: string; last_reading_value: number }[];
}

export default function RouteScreen() {
  const navigation = useNavigation<any>();
  const { user, logout } = useAuth();
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await api.get<{ items: Customer[] }>('/customers?has_hydrometer=true&status=active&per_page=100');
      setCustomers(res.items);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const onRefresh = () => { setRefreshing(true); load(); };

  if (loading) {
    return (
      <View style={[shared.container, { justifyContent: 'center', alignItems: 'center' }]}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
  }

  return (
    <View style={shared.container}>
      {/* Header */}
      <View style={shared.headerBar}>
        <View>
          <Text style={shared.title}>Rota</Text>
          <Text style={shared.subtitle}>{customers.length} clientes pendentes</Text>
        </View>
        <TouchableOpacity onPress={logout}>
          <Text style={{ color: colors.danger, fontWeight: '600', fontSize: 13 }}>Sair</Text>
        </TouchableOpacity>
      </View>

      <FlatList
        data={customers}
        keyExtractor={c => c.id}
        contentContainerStyle={{ padding: 16 }}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.accent} />}
        renderItem={({ item }) => (
          <TouchableOpacity
            style={styles.customerCard}
            onPress={() => navigation.navigate('Camera', {
              customerId: item.id,
              customerName: item.name,
              hydrometerId: item.hydrometers?.[0]?.id,
              hydrometerCode: item.hydrometers?.[0]?.code,
              lastReading: item.hydrometers?.[0]?.last_reading_value || 0,
            })}
          >
            <View style={styles.customerRow}>
              <View style={styles.avatar}>
                <Text style={styles.avatarText}>{item.name.charAt(0)}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.customerName}>{item.name}</Text>
                <Text style={styles.customerAddr}>{item.address}, {item.city}</Text>
                {item.hydrometers?.[0] && (
                  <Text style={styles.meterInfo}>
                    🔵 {item.hydrometers[0].code} — {item.hydrometers[0].last_reading_value.toFixed(2)} m³
                  </Text>
                )}
              </View>
              <Text style={{ color: colors.accent, fontSize: 20 }}>›</Text>
            </View>
          </TouchableOpacity>
        )}
        ListEmptyComponent={
          <View style={{ alignItems: 'center', paddingTop: 60 }}>
            <Text style={{ color: colors.textMuted, fontSize: 14 }}>Nenhum cliente na rota</Text>
          </View>
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  customerCard: {
    backgroundColor: colors.navy800,
    borderRadius: 14,
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
    width: 42,
    height: 42,
    borderRadius: 10,
    backgroundColor: 'rgba(59,130,246,0.12)',
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
    fontWeight: '700',
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
    marginTop: 4,
  },
});
