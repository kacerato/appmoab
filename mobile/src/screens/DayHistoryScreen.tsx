import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, FlatList, Text, TouchableOpacity, View } from 'react-native';
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

  useEffect(() => {
    api.get<{ items: ReadingItem[] }>('/readings?per_page=200')
      .then(res => {
        const todayKey = new Date().toISOString().slice(0, 10);
        setReadings(res.items.filter(item => item.collaborator_id === user?.id && item.captured_at.slice(0, 10) === todayKey));
      })
      .catch(error => {
        console.error(error);
        showToast('Falha ao carregar histórico', error instanceof Error ? error.message : 'Não foi possível carregar o histórico do dia.', 'error');
      })
      .finally(() => setLoading(false));
  }, [showToast, user?.id]);

  const counts = useMemo(() => ({
    approved: readings.filter(item => item.status === 'approved').length,
    pending: readings.filter(item => item.status === 'pending').length,
    rejected: readings.filter(item => item.status === 'rejected').length,
  }), [readings]);

  return (
    <View style={shared.container}>
      <View style={shared.headerBar}>
        <View>
          <Text style={shared.title}>Histórico do dia</Text>
          <Text style={shared.subtitle}>Leituras feitas por você hoje</Text>
        </View>
        <TouchableOpacity onPress={() => navigation.goBack()}>
          <Text style={{ color: colors.accent, fontWeight: '700', fontSize: 13 }}>Voltar</Text>
        </TouchableOpacity>
      </View>

      {loading ? (
        <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center' }}>
          <ActivityIndicator size="large" color={colors.accent} />
        </View>
      ) : (
        <FlatList
          data={readings}
          keyExtractor={item => item.id}
          contentContainerStyle={{ padding: 16, paddingBottom: 32 }}
          ListHeaderComponent={
            <View style={shared.card}>
              <Text style={shared.sectionTitle}>Resumo</Text>
              <Text style={{ color: colors.textSecondary, fontSize: 13, lineHeight: 20 }}>
                {counts.approved} aprovadas · {counts.pending} aguardando aprovação · {counts.rejected} rejeitadas
              </Text>
            </View>
          }
          renderItem={({ item }) => (
            <View style={shared.card}>
              <Text style={{ color: colors.textPrimary, fontWeight: '800', fontSize: 15 }}>{item.customer_name || 'Cliente'}</Text>
              <Text style={{ color: colors.textMuted, fontSize: 12, marginTop: 3 }}>{item.hydrometer_code || 'Sem código'} · {new Date(item.captured_at).toLocaleTimeString('pt-BR')}</Text>
              <Text style={{ color: colors.textSecondary, fontSize: 13, marginTop: 10 }}>
                Leitura: {item.current_value.toFixed(2)} m³ · Consumo: {item.consumption.toFixed(2)} m³
              </Text>
              <View style={[shared.badge, {
                backgroundColor:
                  item.status === 'approved' ? colors.successSoft :
                  item.status === 'rejected' ? colors.dangerSoft : colors.warningSoft,
                marginTop: 12,
              }]}>
                <Text style={[shared.badgeText, {
                  color:
                    item.status === 'approved' ? colors.success :
                    item.status === 'rejected' ? colors.danger : colors.warning,
                }]}>
                  {item.status === 'approved' ? 'Aprovada' : item.status === 'rejected' ? 'Rejeitada' : 'Pendente'}
                </Text>
              </View>
            </View>
          )}
          ListEmptyComponent={
            <View style={{ alignItems: 'center', paddingTop: 80 }}>
              <Text style={{ color: colors.textMuted, fontSize: 14 }}>Nenhuma leitura registrada hoje.</Text>
            </View>
          }
        />
      )}
    </View>
  );
}
