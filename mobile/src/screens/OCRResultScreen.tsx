import React, { useEffect, useState } from 'react';
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet,
  ActivityIndicator, ScrollView, Alert, Image,
} from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import { api } from '../lib/api';
import { colors, shared } from '../styles/theme';

export default function OCRResultScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const {
    photoBase64, photoUri, latitude, longitude, capturedAt,
    hydrometerId, hydrometerCode, customerName, lastReading,
  } = route.params;

  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [ocrData, setOcrData] = useState<any>(null);
  const [currentValue, setCurrentValue] = useState('');
  const [readingId, setReadingId] = useState('');

  useEffect(() => {
    sendForOCR();
  }, []);

  const sendForOCR = async () => {
    try {
      const result = await api.post<any>('/readings', {
        hydrometer_id: hydrometerId,
        photo_base64: photoBase64,
        latitude,
        longitude,
        captured_at: capturedAt,
      });
      setOcrData(result);
      setReadingId(result.reading_id);
      if (result.extracted_value) {
        setCurrentValue(result.extracted_value.toString());
      }
    } catch (err: any) {
      Alert.alert('Erro OCR', err.message || 'Falha no processamento');
    } finally {
      setLoading(false);
    }
  };

  const confirmReading = async () => {
    if (!currentValue || !readingId) return;
    setSubmitting(true);
    try {
      await api.put(`/readings/${readingId}/confirm`, {
        current_value: parseFloat(currentValue),
        confirmed_code: ocrData?.extracted_code || null,
      });
      Alert.alert('Sucesso!', 'Leitura enviada para aprovação.', [
        { text: 'OK', onPress: () => navigation.navigate('Route') },
      ]);
    } catch (err: any) {
      Alert.alert('Erro', err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const consumption = currentValue ? Math.max(0, parseFloat(currentValue) - lastReading) : 0;
  const confidence = ocrData?.confidence ? Math.round(ocrData.confidence * 100) : 0;

  return (
    <ScrollView style={shared.container} contentContainerStyle={{ padding: 20 }}>
      {/* Header */}
      <View style={{ flexDirection: 'row', justifyContent: 'space-between', marginBottom: 20 }}>
        <TouchableOpacity onPress={() => navigation.goBack()}>
          <Text style={{ color: colors.accent, fontWeight: '600' }}>← Voltar</Text>
        </TouchableOpacity>
        <Text style={{ color: colors.textPrimary, fontWeight: '700' }}>{customerName}</Text>
      </View>

      {/* Foto capturada */}
      {photoUri && (
        <Image source={{ uri: photoUri }} style={styles.photo} resizeMode="cover" />
      )}

      {loading ? (
        <View style={{ alignItems: 'center', paddingVertical: 40 }}>
          <ActivityIndicator size="large" color={colors.accent} />
          <Text style={{ color: colors.textMuted, marginTop: 12, fontSize: 13 }}>
            Processando imagem com IA...
          </Text>
        </View>
      ) : (
        <>
          {/* Resultado OCR */}
          <View style={shared.card}>
            <Text style={{ color: colors.textMuted, fontSize: 11, fontWeight: '700', marginBottom: 12, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              Resultado do OCR
            </Text>

            <View style={styles.ocrGrid}>
              <View style={styles.ocrItem}>
                <Text style={styles.ocrLabel}>Código</Text>
                <Text style={styles.ocrValue}>{ocrData?.extracted_code || '—'}</Text>
              </View>
              <View style={styles.ocrItem}>
                <Text style={styles.ocrLabel}>Leitura Extraída</Text>
                <Text style={[styles.ocrValue, { color: colors.cyan }]}>
                  {ocrData?.extracted_value?.toFixed(2) || '—'} m³
                </Text>
              </View>
              <View style={styles.ocrItem}>
                <Text style={styles.ocrLabel}>Confiança</Text>
                <Text style={[styles.ocrValue, {
                  color: confidence >= 80 ? colors.success : confidence >= 50 ? colors.warning : colors.danger,
                }]}>
                  {confidence}%
                </Text>
              </View>
            </View>
          </View>

          {/* Validação manual */}
          <View style={shared.card}>
            <Text style={{ color: colors.textMuted, fontSize: 11, fontWeight: '700', marginBottom: 12, textTransform: 'uppercase', letterSpacing: 0.5 }}>
              Confirme a Leitura
            </Text>

            <View style={{ marginBottom: 16 }}>
              <Text style={shared.label}>Leitura Atual (m³)</Text>
              <TextInput
                style={[shared.input, { fontSize: 24, fontWeight: '800', textAlign: 'center' }]}
                value={currentValue}
                onChangeText={setCurrentValue}
                keyboardType="decimal-pad"
                placeholder="0.00"
                placeholderTextColor={colors.textMuted}
              />
            </View>

            <View style={styles.summaryRow}>
              <View>
                <Text style={styles.sumLabel}>Anterior</Text>
                <Text style={styles.sumValue}>{lastReading.toFixed(2)} m³</Text>
              </View>
              <View>
                <Text style={styles.sumLabel}>Consumo</Text>
                <Text style={[styles.sumValue, { color: colors.cyan, fontSize: 18 }]}>
                  {consumption.toFixed(2)} m³
                </Text>
              </View>
            </View>
          </View>

          {/* Botões */}
          <TouchableOpacity
            style={[shared.btnPrimary, { marginTop: 8 }, submitting && { opacity: 0.5 }]}
            onPress={confirmReading}
            disabled={submitting || !currentValue}
          >
            {submitting ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text style={shared.btnPrimaryText}>✓ Confirmar e Enviar</Text>
            )}
          </TouchableOpacity>

          <TouchableOpacity
            style={[shared.btnSecondary, { marginTop: 10 }]}
            onPress={() => navigation.goBack()}
          >
            <Text style={shared.btnSecondaryText}>Refazer Foto</Text>
          </TouchableOpacity>
        </>
      )}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  photo: {
    width: '100%',
    height: 200,
    borderRadius: 14,
    marginBottom: 16,
    backgroundColor: colors.navy800,
  },
  ocrGrid: {
    flexDirection: 'row',
    gap: 12,
  },
  ocrItem: { flex: 1 },
  ocrLabel: { color: colors.textMuted, fontSize: 11, marginBottom: 4 },
  ocrValue: { color: colors.textPrimary, fontSize: 15, fontWeight: '700' },
  summaryRow: {
    flexDirection: 'row',
    justifyContent: 'space-around',
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: colors.border,
  },
  sumLabel: { color: colors.textMuted, fontSize: 11, textAlign: 'center', marginBottom: 4 },
  sumValue: { color: colors.textPrimary, fontSize: 15, fontWeight: '700', textAlign: 'center' },
});
