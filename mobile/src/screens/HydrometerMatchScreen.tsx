import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Image, ScrollView, Text, TouchableOpacity, View } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { api } from '../lib/api';
import { useFeedback } from '../lib/feedback';
import { colors, shared } from '../styles/theme';

interface IdentifyResult {
  extracted_code: string | null;
  confidence: number | null;
  matched: boolean;
  hydrometer_id: string | null;
  hydrometer_code: string | null;
  customer_id: string | null;
  customer_name: string | null;
  location_description: string | null;
  last_reading_value: number | null;
}

export default function HydrometerMatchScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const { showToast } = useFeedback();
  const {
    photoBase64,
    photoUri,
    expectedCustomerId,
    expectedCustomerName,
    expectedHydrometerId,
    expectedHydrometerCode,
    lastReading,
    locationDescription,
  } = route.params;

  const [loading, setLoading] = useState(true);
  const [result, setResult] = useState<IdentifyResult | null>(null);

  useEffect(() => {
    api.post<IdentifyResult>('/hydrometers/identify', { photo_base64: photoBase64 })
      .then(setResult)
      .catch(error => {
        console.error(error);
        showToast('Falha ao identificar código', error instanceof Error ? error.message : 'Não foi possível validar o hidrômetro.', 'error');
      })
      .finally(() => setLoading(false));
  }, [photoBase64, showToast]);

  const associationState = useMemo(() => {
    if (!result?.matched) {
      return {
        ok: false,
        title: 'Código não localizado no cadastro',
        description: 'Refaça a captura do código ou verifique se o hidrômetro já foi cadastrado no painel.',
      };
    }

    if (result.customer_id !== expectedCustomerId || result.hydrometer_id !== expectedHydrometerId) {
      return {
        ok: false,
        title: 'Associação divergente da rota',
        description: `A foto aponta para ${result.customer_name || 'outro cliente'}, mas a rota aberta é de ${expectedCustomerName}.`,
      };
    }

    return {
      ok: true,
      title: 'Associação confirmada',
      description: 'Código, cliente e hidrômetro batem com a rota selecionada.',
    };
  }, [expectedCustomerId, expectedCustomerName, expectedHydrometerId, result]);

  const continueToReading = () => {
    if (!result?.matched || !associationState.ok) return;
    navigation.navigate('Camera', {
      stage: 'reading',
      hydrometerId: result.hydrometer_id,
      hydrometerCode: result.hydrometer_code,
      customerName: result.customer_name || expectedCustomerName,
      lastReading: result.last_reading_value ?? lastReading,
      locationDescription: result.location_description || locationDescription,
    });
  };

  return (
    <ScrollView style={shared.container} contentContainerStyle={{ padding: 20, paddingBottom: 32 }}>
      <TouchableOpacity onPress={() => navigation.goBack()}>
        <Text style={{ color: colors.accent, fontWeight: '700', marginBottom: 16 }}>← Refazer código</Text>
      </TouchableOpacity>

      {photoUri ? (
        <Image source={{ uri: photoUri }} style={{ width: '100%', height: 180, borderRadius: 16, marginBottom: 16, backgroundColor: colors.navy700 }} />
      ) : null}

      {loading ? (
        <View style={shared.card}>
          <ActivityIndicator size="large" color={colors.accent} />
          <Text style={{ marginTop: 14, color: colors.textMuted, textAlign: 'center' }}>
            Validando o código do hidrômetro...
          </Text>
        </View>
      ) : (
        <>
          <View style={shared.card}>
            <Text style={shared.sectionTitle}>Conferência da associação</Text>
            <Text style={{ color: associationState.ok ? colors.success : colors.danger, fontSize: 15, fontWeight: '800' }}>
              {associationState.title}
            </Text>
            <Text style={{ color: colors.textSecondary, fontSize: 13, lineHeight: 20, marginTop: 8 }}>
              {associationState.description}
            </Text>
          </View>

          <View style={shared.card}>
            <Text style={shared.sectionTitle}>Dados do código</Text>
            <Field label="Código esperado" value={expectedHydrometerCode} />
            <Field label="Código extraído" value={result?.extracted_code || 'Não identificado'} />
            <Field label="Confiança do OCR" value={`${Math.round((result?.confidence || 0) * 100)}%`} />
            <Field label="Cliente da rota" value={expectedCustomerName} />
            <Field label="Cliente identificado" value={result?.customer_name || 'Sem correspondência'} />
            <Field label="Local de referência" value={result?.location_description || locationDescription || 'Não informado'} />
          </View>

          <TouchableOpacity
            style={[shared.btnPrimary, { marginTop: 10 }, (!associationState.ok || !result?.matched) && { opacity: 0.45 }]}
            disabled={!associationState.ok || !result?.matched}
            onPress={continueToReading}
          >
            <Text style={shared.btnPrimaryText}>Seguir para a leitura</Text>
          </TouchableOpacity>

          <TouchableOpacity
            style={[shared.btnSecondary, { marginTop: 10 }]}
            onPress={() => navigation.goBack()}
          >
            <Text style={shared.btnSecondaryText}>Capturar código novamente</Text>
          </TouchableOpacity>
        </>
      )}
    </ScrollView>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={{ color: colors.textMuted, fontSize: 11, fontWeight: '700', marginBottom: 4 }}>{label}</Text>
      <Text style={{ color: colors.textPrimary, fontSize: 14, fontWeight: '600' }}>{value}</Text>
    </View>
  );
}
