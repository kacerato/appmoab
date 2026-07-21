import React, { useEffect, useMemo, useState } from 'react';
import { ActivityIndicator, Image, StyleSheet, Text, TextInput, TouchableOpacity, View } from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { api } from '../lib/api';
import { useFeedback } from '../lib/feedback';
import { useMobileTheme } from '../lib/mobile-theme';
import { colors, shared } from '../styles/theme';

interface VisionVerdict {
  predicted_code: string | null;
  predicted_value: number | null;
  confidence: number | null;
  red_digits: number | null;
  black_digits: number | null;
}

export default function ManualCodeScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const { showToast } = useFeedback();
  const { mode } = useMobileTheme();
  const styles = useMemo(createStyles, [mode]);
  const {
    photoBase64,
    photoUri,
    expectedCustomerId,
    expectedCustomerName,
    expectedHydrometerId,
    expectedHydrometerCode,
    lastReading,
    redDigits = 3,
    blackDigits = null,
    hydrometerBrand = '',
    hydrometerModel = '',
    locationDescription,
    isInstallation = false,
  } = route.params;
  const [code, setCode] = useState(expectedHydrometerCode || '');
  const [submitting, setSubmitting] = useState(false);
  const [verdict, setVerdict] = useState<VisionVerdict | null>(null);

  useEffect(() => {
    api.post<VisionVerdict>('/hydrometers/vision-verdict', { photo_base64: photoBase64 })
      .then(setVerdict)
      .catch(() => setVerdict(null));
  }, [photoBase64]);

  const validateCode = async () => {
    if (!code.trim()) return;
    setSubmitting(true);
    try {
      const result = await api.post<any>('/hydrometers/resolve-code', { code });
      await api.post('/hydrometers/vision-feedback', {
        photo_base64: photoBase64,
        stage: 'code',
        predicted_code: verdict?.predicted_code || null,
        confidence: verdict?.confidence || null,
        confirmed_code: code,
        hydrometer_id: result.hydrometer_id || expectedHydrometerId || null,
        red_digits: result.red_digits || redDigits,
        black_digits: result.black_digits || blackDigits,
        hydrometer_brand: result.brand || hydrometerBrand || null,
        hydrometer_model: result.model || hydrometerModel || null,
      }).catch(() => null);

      if (!result.matched) {
        showToast('Codigo nao encontrado', 'Confira o numero digitado ou cadastre o hidrometro no painel.', 'warning');
        return;
      }

      if (expectedHydrometerId && result.hydrometer_id !== expectedHydrometerId) {
        showToast('Codigo fora da rota', `O codigo pertence a ${result.customer_name || 'outro cliente'}.`, 'error');
        return;
      }

      navigation.navigate('Camera', {
        stage: 'reading',
        hydrometerId: result.hydrometer_id,
        hydrometerCode: result.hydrometer_code,
        customerName: result.customer_name || expectedCustomerName || 'Leitura manual',
        lastReading: result.last_reading_value ?? lastReading,
        redDigits: result.red_digits || redDigits,
        blackDigits: result.black_digits || blackDigits,
        hydrometerBrand: result.brand || hydrometerBrand,
        hydrometerModel: result.model || hydrometerModel,
        locationDescription: result.location_description || locationDescription,
        isInstallation: result.last_reading_date === null || result.last_reading_date === undefined ? true : isInstallation,
      });
    } catch (error) {
      showToast('Falha ao validar codigo', error instanceof Error ? error.message : 'Nao foi possivel validar o codigo.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View style={shared.container}>
      <View style={styles.content}>
        <TouchableOpacity onPress={() => navigation.goBack()}>
          <Text style={styles.backLink}>Refazer foto do codigo</Text>
        </TouchableOpacity>
        {photoUri ? <Image source={{ uri: photoUri }} style={styles.previewImage} /> : null}
        <View style={shared.card}>
          <Text style={shared.sectionTitle}>Codigo do hidrometro</Text>
          <Text style={styles.title}>Digite o codigo fotografado</Text>
          <Text style={styles.subtitle}>
            A foto fica salva para o GLM-OCR avaliar por baixo dos panos, mas quem confirma o codigo agora e voce.
          </Text>
          <TextInput
            style={styles.codeInput}
            value={code}
            onChangeText={setCode}
            keyboardType="number-pad"
            placeholder="000001"
            placeholderTextColor={colors.textMuted}
          />
          <TouchableOpacity
            style={[shared.btnPrimary, submitting && { opacity: 0.55 }]}
            onPress={validateCode}
            disabled={submitting || !code.trim()}
          >
            {submitting ? <ActivityIndicator color="#fff" /> : <Text style={shared.btnPrimaryText}>Validar e fotografar leitura</Text>}
          </TouchableOpacity>
        </View>
      </View>
    </View>
  );
}

function createStyles() {
  return StyleSheet.create({
  content: { flex: 1, padding: 20, paddingTop: 48 },
  backLink: { color: colors.cyan, fontSize: 12, fontWeight: '900', textTransform: 'uppercase', marginBottom: 14 },
  previewImage: { width: '100%', height: 180, borderRadius: 18, marginBottom: 16, backgroundColor: colors.navy700 },
  title: { color: colors.textPrimary, fontSize: 22, fontWeight: '900', marginBottom: 8 },
  subtitle: { color: colors.textSecondary, fontSize: 13, lineHeight: 20, marginBottom: 18 },
  codeInput: {
    backgroundColor: colors.navy900,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 18,
    color: colors.textPrimary,
    fontSize: 30,
    fontWeight: '900',
    textAlign: 'center',
    paddingVertical: 16,
    marginBottom: 16,
  },
  });
}
