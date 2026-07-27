import React, { useCallback, useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Image,
  ScrollView,
  Text,
  TouchableOpacity,
  View,
} from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { api } from '../lib/api';
import { useFeedback } from '../lib/feedback';
import { colors, shared } from '../styles/theme';

interface OCRData {
  reading_id: string;
  extracted_code: string | null;
  extracted_value: number | null;
  confidence: number | null;
  matched_customer_name: string | null;
  matched_hydrometer_code: string | null;
}

interface VisionVerdict {
  inference_id: string | null;
  predicted_code: string | null;
  predicted_value: number | null;
  confidence: number | null;
  auto_fill_allowed: boolean;
  decision?: 'accepted' | 'confirm' | 'recapture' | 'unsupported';
}

export default function OCRResultScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const { showToast } = useFeedback();
  const {
    photoBase64,
    photoUri,
    framesBase64 = [],
    captureId,
    captureMetadata = {},
    frameMetadata = [],
    latitude,
    longitude,
    locationAccuracyMeters,
    capturedAt,
    hydrometerId,
    lastReading,
    redDigits = 3,
    blackDigits = null,
    hydrometerBrand = '',
    hydrometerModel = '',
    isInstallation = false,
    cycleId = null,
  } = route.params;

  const [submitting, setSubmitting] = useState(false);
  const verdictRef = useRef<VisionVerdict | null>(null);
  const verdictPromiseRef = useRef<Promise<VisionVerdict | null> | null>(null);
  const processingStartedRef = useRef(false);
  const selectedRedDigits = Number(redDigits || 3);

  useEffect(() => {
    if (processingStartedRef.current) return;
    processingStartedRef.current = true;

    // A análise pode começar enquanto o operador confere a foto, mas a leitura
    // só será criada depois do toque explícito no botão de confirmação.
    const pendingVerdict = api.post<VisionVerdict>('/hydrometers/vision-verdict', {
      photo_base64: photoBase64,
      frames_base64: framesBase64,
      capture_id: captureId || null,
      capture_metadata: captureMetadata,
      frame_metadata: frameMetadata,
      hydrometer_id: hydrometerId,
      stage: 'reading',
      red_digits: selectedRedDigits,
      black_digits: blackDigits,
      previous_value: lastReading,
      hydrometer_brand: hydrometerBrand || null,
      hydrometer_model: hydrometerModel || null,
    }, 75000)
      .then(result => {
        verdictRef.current = result;
        return result;
      })
      .catch(() => null);

    verdictPromiseRef.current = pendingVerdict;
  }, [
    blackDigits,
    captureId,
    captureMetadata,
    frameMetadata,
    framesBase64,
    hydrometerBrand,
    hydrometerId,
    hydrometerModel,
    lastReading,
    photoBase64,
    selectedRedDigits,
  ]);

  const submitCapture = useCallback(async (resolvedVerdict: VisionVerdict | null) => {
    const inferenceId = resolvedVerdict?.inference_id || null;
    const payload = {
      hydrometer_id: hydrometerId,
      // Quando ha inferencia, o backend reutiliza a foto primaria que ja foi
      // armazenada. O base64 so segue como fallback se a analise falhar.
      ...(inferenceId ? {} : { photo_base64: photoBase64 }),
      latitude,
      longitude,
      location_accuracy_meters: locationAccuracyMeters,
      captured_at: capturedAt,
      vision_inference_id: inferenceId,
      cycle_id: cycleId,
    };

    await api.post<OCRData>('/readings', payload);
    showToast(
      isInstallation ? 'Captura da instalação enviada' : 'Leitura capturada',
      'A leitura foi enviada para confirmação no dashboard.',
      'success',
    );
    navigation.navigate('Route', { refreshToken: Date.now() });
  }, [
    capturedAt,
    cycleId,
    hydrometerId,
    isInstallation,
    latitude,
    locationAccuracyMeters,
    longitude,
    navigation,
    photoBase64,
    showToast,
  ]);

  const confirmReading = async () => {
    if (submitting) return;
    setSubmitting(true);
    try {
      const resolvedVerdict = verdictRef.current || await verdictPromiseRef.current;
      await submitCapture(resolvedVerdict);
    } catch (error) {
      showToast(
        'Falha ao enviar captura',
        error instanceof Error ? error.message : 'Não foi possível enviar a captura.',
        'error',
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ScrollView
      style={shared.container}
      contentContainerStyle={{
        flexGrow: 1,
        padding: 20,
        paddingBottom: 32,
        justifyContent: 'center',
      }}
    >
      <TouchableOpacity
        onPress={() => navigation.goBack()}
        disabled={submitting}
        style={{ alignSelf: 'flex-start', marginBottom: 18 }}
      >
        <Text style={{ color: colors.accent, fontWeight: '700' }}>
          ← Tirar outra foto
        </Text>
      </TouchableOpacity>

      {photoUri ? (
        <Image
          source={{ uri: photoUri }}
          resizeMode="contain"
          style={{
            width: '100%',
            height: 300,
            borderRadius: 18,
            marginBottom: 24,
            backgroundColor: colors.navy700,
          }}
        />
      ) : null}

      <View style={[shared.card, { alignItems: 'center', paddingVertical: 28 }]}>
        <Text
          style={{
            color: colors.textPrimary,
            fontSize: 22,
            lineHeight: 29,
            fontWeight: '800',
            textAlign: 'center',
          }}
        >
          Tem certeza de que deseja confirmar esta leitura?
        </Text>
        <Text
          style={{
            color: colors.textSecondary,
            fontSize: 14,
            lineHeight: 21,
            textAlign: 'center',
            marginTop: 10,
          }}
        >
          Ela só será enviada para revisão no dashboard depois da sua confirmação.
        </Text>
      </View>

      <TouchableOpacity
        style={[shared.btnPrimary, submitting && { opacity: 0.65 }]}
        onPress={confirmReading}
        disabled={submitting}
      >
        {submitting ? (
          <ActivityIndicator color="#fff" />
        ) : (
          <Text style={shared.btnPrimaryText}>Sim, confirmar leitura</Text>
        )}
      </TouchableOpacity>
    </ScrollView>
  );
}
