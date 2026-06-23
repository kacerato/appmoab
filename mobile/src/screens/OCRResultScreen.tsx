import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  ScrollView,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { api } from '../lib/api';
import { useFeedback } from '../lib/feedback';
import { formatMeterReading, parseMeterReadingInput } from '../lib/meter-reading';
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
  red_digits: number | null;
  black_digits: number | null;
  quality?: { usable?: boolean; recapture_reason?: string | null };
  flags?: string[];
}

export default function OCRResultScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const { showToast } = useFeedback();
  const {
    photoBase64,
    photoUri,
    framesBase64 = [],
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
  const [ocrData, setOcrData] = useState<OCRData | null>(null);
  const [currentValue, setCurrentValue] = useState('');
  const [selectedRedDigits, setSelectedRedDigits] = useState<number>(redDigits || 3);
  const [readingId, setReadingId] = useState('');
  const [verdict, setVerdict] = useState<VisionVerdict | null>(null);

  const normalizedCurrentValue = useMemo(
    () => parseMeterReadingInput(currentValue, selectedRedDigits),
    [currentValue, selectedRedDigits],
  );

  useEffect(() => {
    setLoading(false);
    api.post<VisionVerdict>('/hydrometers/vision-verdict', {
      photo_base64: photoBase64,
      frames_base64: framesBase64,
      hydrometer_id: hydrometerId,
      stage: 'reading',
      red_digits: selectedRedDigits,
      black_digits: blackDigits,
      previous_value: lastReading,
      hydrometer_brand: hydrometerBrand || null,
      hydrometer_model: hydrometerModel || null,
    }, 75000)
      .then(result => {
        setVerdict(result);
        if (result.auto_fill_allowed && result.predicted_value !== null) {
          setCurrentValue(current => current || String(result.predicted_value));
        }
      })
      .catch(() => setVerdict(null));
  }, [blackDigits, framesBase64, hydrometerBrand, hydrometerId, hydrometerModel, lastReading, photoBase64, selectedRedDigits]);

  const confirmReading = async () => {
    if (normalizedCurrentValue === null) return;
    const rolloverLimit = 10 ** (blackDigits || 4);
    const isRollover = normalizedCurrentValue < lastReading && lastReading >= rolloverLimit * 0.9;
    if (!isInstallation && normalizedCurrentValue < lastReading && !isRollover) {
      Alert.alert(
        'Leitura menor que a anterior',
        'Confira se o QR e o hidrômetro estão corretos. Essa leitura não será enviada como leitura normal.',
      );
      return;
    }

    setSubmitting(true);
    try {
      const result = await api.post<OCRData>('/readings', {
        hydrometer_id: hydrometerId,
        photo_base64: photoBase64,
        latitude,
        longitude,
        location_accuracy_meters: locationAccuracyMeters,
        captured_at: capturedAt,
        current_value: normalizedCurrentValue,
        confirmed_code: hydrometerCode || null,
        vision_inference_id: verdict?.inference_id || null,
      });
      setOcrData(result);
      setReadingId(result.reading_id);
      await api.post('/hydrometers/vision-feedback', {
        inference_id: verdict?.inference_id || null,
        photo_base64: photoBase64,
        stage: 'reading',
        predicted_code: verdict?.predicted_code || null,
        predicted_value: verdict?.predicted_value || null,
        confidence: verdict?.confidence || null,
        confirmed_code: hydrometerCode || null,
        confirmed_value: normalizedCurrentValue,
        hydrometer_id: hydrometerId,
        red_digits: selectedRedDigits,
        black_digits: blackDigits || verdict?.black_digits || null,
        hydrometer_brand: hydrometerBrand || null,
        hydrometer_model: hydrometerModel || null,
      }).catch(() => null);
      showToast(
        isInstallation ? 'Instalacao enviada' : 'Leitura enviada',
        isInstallation
          ? 'A instalacao foi registrada e aguarda aprovação para gerar o boleto.'
          : 'A leitura foi registrada e aguarda aprovação no painel.',
        'success',
      );
      navigation.navigate('Route');
    } catch (error) {
      showToast('Falha ao confirmar leitura', error instanceof Error ? error.message : 'Não foi possível enviar a leitura.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const consumption = useMemo(() => {
    if (normalizedCurrentValue === null) return 0;
    const rolloverLimit = 10 ** (blackDigits || 4);
    if (!isInstallation && normalizedCurrentValue < lastReading && lastReading >= rolloverLimit * 0.9) {
      return (rolloverLimit - lastReading) + normalizedCurrentValue;
    }
    return Math.max(0, normalizedCurrentValue - lastReading);
  }, [blackDigits, isInstallation, lastReading, normalizedCurrentValue]);
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
        <Image source={{ uri: photoUri }} style={{ width: '100%', height: 200, borderRadius: 16, marginBottom: 16, backgroundColor: colors.navy700 }} />
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

          {verdict?.quality?.usable === false && (
            <View style={[shared.card, { borderColor: colors.warning, borderWidth: 1 }] }>
              <Text style={[shared.sectionTitle, { color: colors.warning }]}>Foto precisa de atenção</Text>
              <Text style={{ color: colors.textSecondary, fontSize: 13, lineHeight: 19 }}>
                {verdict.quality.recapture_reason || 'A visão local encontrou baixa qualidade. Confirme manualmente ou refaça a captura.'}
              </Text>
            </View>
          )}

          <View style={shared.card}>
            <Text style={shared.sectionTitle}>{isInstallation ? 'Valor inicial informado' : 'Leitura digitada'}</Text>
            <View style={{ flexDirection: 'row', gap: 12 }}>
              <Metric label={isInstallation ? 'Base anterior' : 'Anterior'} value={`${formatMeterReading(lastReading)} m³`} />
              <Metric label={isInstallation ? 'Valor inicial' : 'Consumo'} value={`${formatMeterReading(isInstallation ? (normalizedCurrentValue || 0) : consumption)} m³`} accent />
            </View>
          </View>

          <View style={shared.card}>
            <Text style={shared.sectionTitle}>{isInstallation ? 'Confirmar valor do hidrometro' : 'Confirmar a leitura final'}</Text>
            <Text style={shared.label}>Dígitos vermelhos do hidrômetro</Text>
            <View style={{ flexDirection: 'row', gap: 10, marginBottom: 14 }}>
              <RedDigitOption value={2} selected={selectedRedDigits === 2} onPress={() => setSelectedRedDigits(2)} />
              <RedDigitOption value={3} selected={selectedRedDigits === 3} onPress={() => setSelectedRedDigits(3)} />
            </View>
            <Text style={shared.label}>Leitura atual do visor</Text>
            <TextInput
              style={[shared.input, { fontSize: 24, fontWeight: '800', textAlign: 'center', marginBottom: 16 }]}
              value={currentValue}
              onChangeText={setCurrentValue}
              keyboardType="decimal-pad"
              placeholder="Ex: 0013440"
              placeholderTextColor={colors.textMuted}
            />
            <Text style={{ color: colors.textMuted, fontSize: 12, lineHeight: 18, marginTop: -8 }}>
              Interpretado como {formatMeterReading(normalizedCurrentValue)} m³ com {selectedRedDigits} dígitos vermelhos.
            </Text>
          </View>

          <TouchableOpacity
            style={[shared.btnPrimary, submitting && { opacity: 0.5 }, normalizedCurrentValue === null && { opacity: 0.45 }]}
            onPress={confirmReading}
            disabled={submitting || normalizedCurrentValue === null}
          >
            {submitting ? <ActivityIndicator color="#fff" /> : <Text style={shared.btnPrimaryText}>{isInstallation ? 'Enviar instalacao' : 'Confirmar e enviar'}</Text>}
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

function RedDigitOption({ value, selected, onPress }: { value: number; selected: boolean; onPress: () => void }) {
  return (
    <TouchableOpacity
      onPress={onPress}
      style={{
        flex: 1,
        borderRadius: 14,
        paddingVertical: 12,
        alignItems: 'center',
        backgroundColor: selected ? colors.dangerSoft : colors.navy700,
        borderWidth: 1,
        borderColor: selected ? colors.danger : colors.border,
      }}
    >
      <Text style={{ color: selected ? colors.danger : colors.textSecondary, fontWeight: '900' }}>{value} vermelhos</Text>
    </TouchableOpacity>
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

function Metric({ label, value, tone, accent }: { label: string; value: string; tone?: 'success' | 'warning' | 'danger'; accent?: boolean }) {
  const color = accent
    ? colors.cyan
    : tone === 'success'
      ? colors.success
      : tone === 'warning'
        ? colors.warning
        : tone === 'danger'
          ? colors.danger
          : colors.textPrimary;

  return (
    <View style={{ flex: 1, backgroundColor: colors.navy700, borderRadius: 14, padding: 14 }}>
      <Text style={{ color: colors.textMuted, fontSize: 11, fontWeight: '700', marginBottom: 6 }}>{label}</Text>
      <Text style={{ color, fontSize: 16, fontWeight: '800' }}>{value}</Text>
    </View>
  );
}
