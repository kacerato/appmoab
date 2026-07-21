import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Image, ScrollView, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { api } from '../lib/api';
import { useFeedback } from '../lib/feedback';
import { useMobileTheme } from '../lib/mobile-theme';
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
  const { mode } = useMobileTheme();
  styles = useMemo(createStyles, [mode]);
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
        showToast('Falha ao identificar codigo', error instanceof Error ? error.message : 'Nao foi possivel validar o hidrometro.', 'error');
      })
      .finally(() => setLoading(false));
  }, [photoBase64, showToast]);

  const associationState = useMemo(() => {
    if (!result?.matched) {
      return {
        ok: false,
        title: 'Codigo nao encontrado',
        description: 'Refaca a captura ou confira se o hidrometro esta cadastrado.',
      };
    }

    const hasExpectedRoute = Boolean(expectedCustomerId && expectedHydrometerId);
    if (hasExpectedRoute && (result.customer_id !== expectedCustomerId || result.hydrometer_id !== expectedHydrometerId)) {
      return {
        ok: false,
        title: 'Associacao divergente',
        description: `A captura indica ${result.customer_name || 'outro cliente'}, diferente da rota aberta.`,
      };
    }

    return {
      ok: true,
      title: hasExpectedRoute ? 'Associacao confirmada' : 'Hidrometro localizado',
      description: hasExpectedRoute
        ? 'Cliente e hidrometro conferem com a rota selecionada.'
        : 'O hidrometro foi encontrado. Agora siga para a leitura.',
    };
  }, [expectedCustomerId, expectedHydrometerId, result]);

  const continueToReading = () => {
    if (!result?.matched || !associationState.ok) return;
    navigation.navigate('Camera', {
      stage: 'reading',
      hydrometerId: result.hydrometer_id,
      hydrometerCode: result.hydrometer_code,
      customerName: result.customer_name || expectedCustomerName || 'Escaneamento manual',
      lastReading: result.last_reading_value ?? lastReading,
      locationDescription: result.location_description || locationDescription,
    });
  };

  return (
    <ScrollView style={shared.container} contentContainerStyle={{ padding: 16, paddingBottom: 32 }}>
      <TouchableOpacity onPress={() => navigation.goBack()}>
        <Text style={styles.backLink}>Refazer codigo</Text>
      </TouchableOpacity>

      {photoUri ? (
        <Image source={{ uri: photoUri }} style={styles.previewImage} />
      ) : null}

      {loading ? (
        <View style={shared.card}>
          <ActivityIndicator size="large" color={colors.accent} />
          <Text style={styles.loadingText}>Validando o codigo...</Text>
        </View>
      ) : (
        <>
          <View style={shared.card}>
            <Text style={shared.sectionTitle}>Conferencia</Text>
            <Text style={[styles.title, { color: associationState.ok ? colors.success : colors.danger }]}>
              {associationState.title}
            </Text>
            <Text style={styles.description}>{associationState.description}</Text>
          </View>

          <View style={shared.card}>
            <Field label="Codigo lido" value={result?.extracted_code || 'Nao identificado'} />
            {!!expectedHydrometerCode && <Field label="Codigo esperado" value={expectedHydrometerCode} />}
            <Field label="Cliente encontrado" value={result?.customer_name || 'Sem correspondencia'} />
            <Field label="Local" value={result?.location_description || locationDescription || 'Nao informado'} />
          </View>

          <TouchableOpacity
            style={[shared.btnPrimary, (!associationState.ok || !result?.matched) && { opacity: 0.45 }]}
            disabled={!associationState.ok || !result?.matched}
            onPress={continueToReading}
          >
            <Text style={shared.btnPrimaryText}>Seguir para leitura</Text>
          </TouchableOpacity>
        </>
      )}
    </ScrollView>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel}>{label}</Text>
      <Text style={styles.fieldValue}>{value}</Text>
    </View>
  );
}

let styles = createStyles();

function createStyles() {
  return StyleSheet.create({
  backLink: {
    color: colors.accent,
    fontWeight: '800',
    marginBottom: 14,
  },
  previewImage: {
    width: '100%',
    height: 180,
    borderRadius: 16,
    marginBottom: 16,
    backgroundColor: colors.navy700,
  },
  loadingText: {
    marginTop: 14,
    color: colors.textMuted,
    textAlign: 'center',
  },
  title: {
    fontSize: 16,
    fontWeight: '900',
  },
  description: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 20,
    marginTop: 8,
  },
  field: {
    marginBottom: 12,
  },
  fieldLabel: {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: '800',
    marginBottom: 4,
    textTransform: 'uppercase',
  },
  fieldValue: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: '700',
  },
  });
}
