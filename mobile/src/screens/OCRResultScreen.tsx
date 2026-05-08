import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
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
import { colors, shared } from '../styles/theme';

interface OCRData {
  reading_id: string;
  extracted_code: string | null;
  extracted_value: number | null;
  confidence: number | null;
  matched_customer_name: string | null;
  matched_hydrometer_code: string | null;
}

export default function OCRResultScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const { showToast } = useFeedback();
  const {
    photoBase64,
    photoUri,
    latitude,
    longitude,
    capturedAt,
    hydrometerId,
    hydrometerCode,
    customerName,
    lastReading,
    locationDescription,
  } = route.params;

  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [ocrData, setOcrData] = useState<OCRData | null>(null);
  const [currentValue, setCurrentValue] = useState('');
  const [readingId, setReadingId] = useState('');

  useEffect(() => {
    api.post<OCRData>('/readings', {
      hydrometer_id: hydrometerId,
      photo_base64: photoBase64,
      latitude,
      longitude,
      captured_at: capturedAt,
    })
      .then(result => {
        setOcrData(result);
        setReadingId(result.reading_id);
        if (result.extracted_value !== null && result.extracted_value !== undefined) {
          setCurrentValue(result.extracted_value.toString());
        }
      })
      .catch(error => {
        showToast('Falha no OCR', error instanceof Error ? error.message : 'Não foi possível processar a leitura.', 'error');
      })
      .finally(() => setLoading(false));
  }, [capturedAt, hydrometerId, latitude, longitude, photoBase64, showToast]);

  const confirmReading = async () => {
    if (!currentValue || !readingId) return;
    setSubmitting(true);
    try {
      await api.put(`/readings/${readingId}/confirm`, {
        current_value: parseFloat(currentValue),
        confirmed_code: ocrData?.extracted_code || hydrometerCode || null,
      });
      showToast('Leitura enviada', 'A leitura foi registrada e aguarda aprovação no painel.', 'success');
      navigation.navigate('Route');
    } catch (error) {
      showToast('Falha ao confirmar leitura', error instanceof Error ? error.message : 'Não foi possível enviar a leitura.', 'error');
    } finally {
      setSubmitting(false);
    }
  };

  const consumption = currentValue ? Math.max(0, parseFloat(currentValue) - lastReading) : 0;
  const confidence = ocrData?.confidence ? Math.round(ocrData.confidence * 100) : 0;
  const codeMatches = !ocrData?.extracted_code || !hydrometerCode || ocrData.extracted_code === hydrometerCode;

  const locationLabel = useMemo(() => {
    if (latitude && longitude) {
      return `${Number(latitude).toFixed(5)}, ${Number(longitude).toFixed(5)}`;
    }
    return 'GPS não disponível';
  }, [latitude, longitude]);

  return (
    <ScrollView style={shared.container} contentContainerStyle={{ padding: 20, paddingBottom: 32 }}>
      <TouchableOpacity onPress={() => navigation.goBack()}>
        <Text style={{ color: colors.accent, fontWeight: '700', marginBottom: 16 }}>← Refazer leitura</Text>
      </TouchableOpacity>

      {photoUri ? (
        <Image source={{ uri: photoUri }} style={{ width: '100%', height: 200, borderRadius: 16, marginBottom: 16, backgroundColor: colors.navy700 }} />
      ) : null}

      {loading ? (
        <View style={shared.card}>
          <ActivityIndicator size="large" color={colors.accent} />
          <Text style={{ marginTop: 14, color: colors.textMuted, textAlign: 'center' }}>
            Processando a leitura com IA...
          </Text>
        </View>
      ) : (
        <>
          <View style={shared.card}>
            <Text style={shared.sectionTitle}>Revisão da associação</Text>
            <Field label="Cliente" value={customerName} />
            <Field label="Código esperado" value={hydrometerCode} />
            <Field label="Código reconhecido" value={ocrData?.extracted_code || 'Não reconhecido'} />
            <Field label="Local do hidrômetro" value={locationDescription || 'Não informado'} />
            <Field label="Localização da coleta" value={locationLabel} />
            <Field label="Capturado em" value={new Date(capturedAt).toLocaleString('pt-BR')} />
            {!codeMatches && (
              <Text style={{ color: colors.danger, fontSize: 12, fontWeight: '700', marginTop: 4 }}>
                O código lido na foto diverge do hidrômetro confirmado na etapa anterior. Revise antes de enviar.
              </Text>
            )}
          </View>

          <View style={shared.card}>
            <Text style={shared.sectionTitle}>Resultado do OCR</Text>
            <View style={{ flexDirection: 'row', gap: 12 }}>
              <Metric label="Leitura extraída" value={ocrData?.extracted_value !== null && ocrData?.extracted_value !== undefined ? `${ocrData.extracted_value.toFixed(2)} m³` : '—'} accent />
              <Metric label="Confiança" value={`${confidence}%`} tone={confidence >= 80 ? 'success' : confidence >= 50 ? 'warning' : 'danger'} />
            </View>
          </View>

          <View style={shared.card}>
            <Text style={shared.sectionTitle}>Confirmar a leitura final</Text>
            <Text style={shared.label}>Leitura atual (m³)</Text>
            <TextInput
              style={[shared.input, { fontSize: 24, fontWeight: '800', textAlign: 'center', marginBottom: 16 }]}
              value={currentValue}
              onChangeText={setCurrentValue}
              keyboardType="decimal-pad"
              placeholder="0.00"
              placeholderTextColor={colors.textMuted}
            />

            <View style={{ flexDirection: 'row', justifyContent: 'space-between' }}>
              <Metric label="Anterior" value={`${lastReading.toFixed(2)} m³`} />
              <Metric label="Consumo" value={`${consumption.toFixed(2)} m³`} accent />
            </View>
          </View>

          <TouchableOpacity
            style={[shared.btnPrimary, submitting && { opacity: 0.5 }, (!currentValue || !codeMatches) && { opacity: 0.45 }]}
            onPress={confirmReading}
            disabled={submitting || !currentValue || !codeMatches}
          >
            {submitting ? <ActivityIndicator color="#fff" /> : <Text style={shared.btnPrimaryText}>Confirmar e enviar</Text>}
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
