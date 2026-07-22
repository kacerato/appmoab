import React, { useEffect, useMemo, useState } from 'react';
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
  calibrated_confidence?: number | null;
  decoder_version?: string | null;
  red_digits: number | null;
  black_digits: number | null;
  quality?: { usable?: boolean; recapture_reason?: string | null };
  flags?: string[];
  digits?: Array<{
    position: number;
    value: number | null;
    confidence: number;
    current_digit?: number | null;
    next_digit?: number | null;
    transition_phase?: number | null;
    transitional?: boolean;
  }>;
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
    hydrometerCode,
    customerName,
    lastReading,
    redDigits = 3,
    blackDigits = null,
    hydrometerBrand = '',
    hydrometerModel = '',
    locationDescription,
    isInstallation = false,
  } = route.params;

  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [verdict, setVerdict] = useState<VisionVerdict | null>(null);
  const selectedRedDigits = Number(redDigits || 3);
  const captureNeedsAttention = Boolean(
    verdict?.quality?.usable === false || verdict?.decision === 'recapture',
  );

  useEffect(() => {
    setLoading(true);
    api.post<VisionVerdict>('/hydrometers/vision-verdict', {
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
      .then(setVerdict)
      .catch(() => setVerdict(null))
      .finally(() => setLoading(false));
  }, [blackDigits, captureId, captureMetadata, frameMetadata, framesBase64, hydrometerBrand, hydrometerId, hydrometerModel, lastReading, photoBase64, selectedRedDigits]);

  const sendCapture = async () => {
    setSubmitting(true);
    try {
      await api.post<OCRData>('/readings', {
        hydrometer_id: hydrometerId,
        photo_base64: photoBase64,
        latitude,
        longitude,
        location_accuracy_meters: locationAccuracyMeters,
        captured_at: capturedAt,
        vision_inference_id: verdict?.inference_id || null,
      });
      showToast(
        isInstallation ? 'Captura da instalacao enviada' : 'Captura enviada',
        isInstallation
          ? 'O valor inicial sera conferido no dashboard antes de gerar a cobranca.'
          : 'O OCR sugerira a medicao e o dashboard fara a confirmacao final.',
        'success',
      );
      navigation.navigate('Route');
    } catch (error) {
      showToast('Falha ao enviar captura', error instanceof Error ? error.message : 'Não foi possível enviar a captura.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const locationLabel = useMemo(() => {
    if (latitude && longitude) {
      return `${Number(latitude).toFixed(5)}, ${Number(longitude).toFixed(5)}`;
    }
    return 'GPS não disponível';
  }, [latitude, longitude]);

  return (
    <ScrollView style={shared.container} contentContainerStyle={{ padding: 20, paddingBottom: 32 }}>
      <TouchableOpacity onPress={() => navigation.goBack()}>
          <Text style={{ color: colors.accent, fontWeight: '700', marginBottom: 16 }}>
            {isInstallation ? '← Refazer instalacao' : '← Refazer leitura'}
          </Text>
      </TouchableOpacity>

      {photoUri ? (
        <Image
          source={{ uri: photoUri }}
          resizeMode="contain"
          style={{ width: '100%', height: 280, borderRadius: 16, marginBottom: 16, backgroundColor: colors.navy700 }}
        />
      ) : null}

      {loading ? (
        <View style={shared.card}>
          <ActivityIndicator size="large" color={colors.accent} />
          <Text style={{ marginTop: 14, color: colors.textMuted, textAlign: 'center' }}>
            Preparando conferência...
          </Text>
        </View>
      ) : (
        <>
          <View style={shared.card}>
            <Text style={shared.sectionTitle}>{isInstallation ? 'Revisao da instalacao' : 'Revisão da associação'}</Text>
            <Field label="Cliente" value={customerName} />
            <Field label="Código esperado" value={hydrometerCode} />
            <Field label="Formato cadastrado" value={`${selectedRedDigits} digitos vermelhos${blackDigits ? `, ${blackDigits} pretos` : ''}`} />
            {!!hydrometerBrand && <Field label="Marca/modelo" value={[hydrometerBrand, hydrometerModel].filter(Boolean).join(' ')} />}
            <Field label="Local do hidrômetro" value={locationDescription || 'Não informado'} />
            <Field label="Localização da coleta" value={locationLabel} />
            <Field label="Capturado em" value={new Date(capturedAt).toLocaleString('pt-BR')} />
          </View>

          {captureNeedsAttention && (
            <View style={[shared.card, { borderColor: colors.warning, borderWidth: 1 }] }>
              <Text style={[shared.sectionTitle, { color: colors.warning }]}>Sugestão para melhorar a leitura automática</Text>
              <Text style={{ color: colors.textSecondary, fontSize: 13, lineHeight: 19 }}>
                {verdict?.quality?.recapture_reason || 'A visão encontrou baixa qualidade nesta captura.'}
                {' '}Você pode refazer a foto ou enviá-la assim mesmo para conferência no dashboard.
              </Text>
            </View>
          )}

          <View style={shared.card}>
            <Text style={shared.sectionTitle}>Conferencia no dashboard</Text>
            <Text style={{ color: colors.textSecondary, fontSize: 13, lineHeight: 20 }}>
              O aplicativo envia somente a foto, o GPS e a analise visual. A medicao oficial e o consumo serao definidos por quem aprovar no dashboard.
            </Text>
          </View>

          <TouchableOpacity
            style={[shared.btnPrimary, submitting && { opacity: 0.45 }]}
            onPress={sendCapture}
            disabled={submitting}
          >
            {submitting ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={shared.btnPrimaryText}>
                {captureNeedsAttention ? 'Enviar assim mesmo para conferência' : 'Enviar captura para conferência'}
              </Text>
            )}
          </TouchableOpacity>

          <TouchableOpacity
            style={[shared.btnSecondary, { marginTop: 10 }]}
            onPress={() => navigation.goBack()}
          >
            <Text style={shared.btnSecondaryText}>Refazer captura</Text>
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
