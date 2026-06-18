import React, { useEffect, useMemo, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Image,
  Modal,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { useNavigation, useRoute } from '@react-navigation/native';
import * as SecureStore from 'expo-secure-store';
import Svg, { Circle, Path } from 'react-native-svg';
import { api } from '../lib/api';
import { useFeedback } from '../lib/feedback';
import { formatMeterReading, parseMeterReadingInput } from '../lib/meter-reading';
import { colors, shared } from '../styles/theme';
import { ROUTE_CACHE_KEY } from '../lib/route-cache';

interface Hydrometer {
  id: string;
  code: string;
  qr_code_token?: string | null;
  last_reading_value: number;
  red_digits?: number | null;
  black_digits?: number | null;
  brand?: string | null;
  model?: string | null;
  location_description?: string | null;
  last_reading_date?: string | null;
}

interface Customer {
  id: string;
  name: string;
  address: string;
  city: string;
  hydrometers: Hydrometer[];
}

interface VisionVerdict {
  inference_id: string | null;
  predicted_code: string | null;
  predicted_value: number | null;
  confidence: number | null;
  auto_fill_allowed: boolean;
  red_digits: number | null;
  black_digits: number | null;
  quality?: {
    blur?: number;
    glare?: number;
    darkness?: number;
    contrast?: number;
    perspective?: number;
    usable?: boolean;
    recapture_reason?: string | null;
  };
  flags?: string[];
  digits?: Array<{
    value: number;
    next?: number;
    phase?: number;
    confidence: number;
    transition?: boolean;
  }>;
  model_version?: string | null;
}

interface FlattenedHydrometer {
  customerName: string;
  hydrometer: Hydrometer;
}

export default function DevVisionTestScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const { showToast } = useFeedback();

  // Selected Hydrometer
  const [selected, setSelected] = useState<FlattenedHydrometer | null>(null);

  // List & Selector Modal state
  const [modalVisible, setModalVisible] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [hydrometersList, setHydrometersList] = useState<FlattenedHydrometer[]>([]);
  const [loadingList, setLoadingList] = useState(false);

  // Verdict processing states
  const [verdictLoading, setVerdictLoading] = useState(false);
  const [verdict, setVerdict] = useState<VisionVerdict | null>(null);

  // User input/feedback states
  const [manualValue, setManualValue] = useState('');
  const [selectedRedDigits, setSelectedRedDigits] = useState<number>(3);
  const [submittingFeedback, setSubmittingFeedback] = useState(false);
  const [testResult, setTestResult] = useState<{
    submitted: boolean;
    wasCorrect: boolean;
    difference: number;
    predicted: number;
    confirmed: number;
  } | null>(null);

  // Params from camera capture
  const params = route.params || {};
  const photoUri = params.photoUri;
  const photoBase64 = params.photoBase64;
  const framesBase64 = params.framesBase64 || [];

  // Load hydrometers from SecureStore route cache
  useEffect(() => {
    const loadHydrometers = async () => {
      setLoadingList(true);
      try {
        const cached = await SecureStore.getItemAsync(ROUTE_CACHE_KEY).catch(() => null);
        let list: FlattenedHydrometer[] = [];

        if (cached) {
          const parsed = JSON.parse(cached) as { customers?: Customer[] };
          if (parsed.customers) {
            parsed.customers.forEach(cust => {
              if (cust.hydrometers && cust.hydrometers.length > 0) {
                cust.hydrometers.forEach(hydro => {
                  list.push({
                    customerName: cust.name,
                    hydrometer: hydro,
                  });
                });
              }
            });
          }
        }

        // If cache empty, query customers endpoint
        if (list.length === 0) {
          const res = await api.get<{ items: Customer[] }>('/customers?has_hydrometer=true&status=active&per_page=150');
          if (res?.items) {
            res.items.forEach(cust => {
              if (cust.hydrometers && cust.hydrometers.length > 0) {
                cust.hydrometers.forEach(hydro => {
                  list.push({
                    customerName: cust.name,
                    hydrometer: hydro,
                  });
                });
              }
            });
          }
        }

        setHydrometersList(list);
      } catch (error) {
        console.error('Erro ao carregar hidrômetros:', error);
      } finally {
        setLoadingList(false);
      }
    };

    void loadHydrometers();
  }, []);

  // Sync selected hydrometer when returning from camera with a selected ID
  useEffect(() => {
    if (params.hydrometerId && hydrometersList.length > 0) {
      const found = hydrometersList.find(h => h.hydrometer.id === params.hydrometerId);
      if (found) {
        setSelected(found);
        setSelectedRedDigits(params.redDigits ?? found.hydrometer.red_digits ?? 3);
      }
    }
  }, [params.hydrometerId, hydrometersList]);

  // When photo is received, call the local vision model verdict API
  useEffect(() => {
    if (photoBase64 && selected) {
      setVerdictLoading(true);
      setVerdict(null);
      setTestResult(null);

      api.post<VisionVerdict>('/hydrometers/vision-verdict', {
        photo_base64: photoBase64,
        frames_base64: framesBase64,
        hydrometer_id: selected.hydrometer.id,
        stage: 'dev_test',
        red_digits: selectedRedDigits,
        black_digits: selected.hydrometer.black_digits,
        previous_value: selected.hydrometer.last_reading_value,
        hydrometer_brand: selected.hydrometer.brand || null,
        hydrometer_model: selected.hydrometer.model || null,
      })
        .then(res => {
          setVerdict(res);
          if (res.predicted_value !== null) {
            setManualValue(String(res.predicted_value));
          } else {
            setManualValue('');
          }
        })
        .catch(err => {
          showToast(
            'Falha na inferência local',
            err instanceof Error ? err.message : 'Erro ao processar imagem no OCR.',
            'error',
          );
        })
        .finally(() => {
          setVerdictLoading(false);
        });
    }
  }, [photoBase64]);

  const filteredHydrometers = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    if (!query) return hydrometersList;
    return hydrometersList.filter(
      item =>
        item.customerName.toLowerCase().includes(query) ||
        item.hydrometer.code.toLowerCase().includes(query),
    );
  }, [hydrometersList, searchQuery]);

  const handleOpenCamera = () => {
    if (!selected) {
      showToast('Selecione um ponto', 'É necessário selecionar um hidrômetro antes de abrir a câmera.', 'warning');
      return;
    }
    navigation.navigate('Camera', {
      stage: 'dev_test',
      expectedCustomerId: null,
      expectedCustomerName: selected.customerName,
      expectedHydrometerId: selected.hydrometer.id,
      expectedHydrometerCode: selected.hydrometer.code,
      expectedQrCodeToken: selected.hydrometer.qr_code_token || null,
      lastReading: selected.hydrometer.last_reading_value || 0,
      redDigits: selectedRedDigits,
      blackDigits: selected.hydrometer.black_digits || null,
      hydrometerBrand: selected.hydrometer.brand || '',
      hydrometerModel: selected.hydrometer.model || '',
      locationDescription: selected.hydrometer.location_description || '',
      isInstallation: !selected.hydrometer.last_reading_date,
    });
  };

  const parsedManualValue = useMemo(() => {
    return parseMeterReadingInput(manualValue, selectedRedDigits);
  }, [manualValue, selectedRedDigits]);

  const submitFeedback = async () => {
    if (!selected || parsedManualValue === null || !photoBase64) return;

    setSubmittingFeedback(true);
    try {
      const predVal = verdict?.predicted_value ?? null;
      const predCode = verdict?.predicted_code ?? null;

      // Submit feedback to populate VisionInference and active_learning dataset
      const res = await api.post<{ was_correct: boolean }>('/hydrometers/vision-feedback', {
        inference_id: verdict?.inference_id || null,
        photo_base64: photoBase64,
        stage: 'dev_test',
        predicted_code: predCode,
        predicted_value: predVal,
        confidence: verdict?.confidence || null,
        confirmed_code: selected.hydrometer.code,
        confirmed_value: parsedManualValue,
        hydrometer_id: selected.hydrometer.id,
        red_digits: selectedRedDigits,
        black_digits: selected.hydrometer.black_digits || verdict?.black_digits || null,
        hydrometer_brand: selected.hydrometer.brand || null,
        hydrometer_model: selected.hydrometer.model || null,
      });

      const wasCorrect = res.was_correct;
      const difference = predVal !== null ? Math.abs(parsedManualValue - predVal) : 0;

      setTestResult({
        submitted: true,
        wasCorrect,
        difference,
        predicted: predVal ?? 0,
        confirmed: parsedManualValue,
      });

      showToast(
        wasCorrect ? 'Sucesso! Acerto' : 'Enviado! Divergência registrada',
        wasCorrect ? 'O motor local acertou a leitura!' : 'A imagem e a correção foram salvas para treinamento.',
        wasCorrect ? 'success' : 'warning',
      );
    } catch (error) {
      showToast(
        'Falha ao enviar feedback',
        error instanceof Error ? error.message : 'Erro na comunicação.',
        'error',
      );
    } finally {
      setSubmittingFeedback(false);
    }
  };

  const resetCapture = () => {
    navigation.setParams({
      photoBase64: null,
      photoUri: null,
      framesBase64: [],
    });
    setVerdict(null);
    setManualValue('');
    setTestResult(null);
  };

  return (
    <ScrollView style={shared.container} contentContainerStyle={{ padding: 20, paddingBottom: 48 }}>
      {/* Header */}
      <View style={styles.header}>
        <TouchableOpacity onPress={() => navigation.navigate('Route')}>
          <Text style={styles.backText}>← Menu Rotas</Text>
        </TouchableOpacity>
        <View style={styles.badgeDev}>
          <Text style={styles.badgeDevText}>DEV VISION MODE</Text>
        </View>
      </View>

      <Text style={styles.title}>Coleta e Testes de OCR</Text>
      <Text style={styles.subtitle}>
        Registre amostras, compare a precisão do motor de visão local e alimente o dataset de treinamento.
      </Text>

      {/* STEP 1: Select Hydrometer */}
      <View style={shared.card}>
        <Text style={shared.sectionTitle}>1. Hidrômetro selecionado</Text>
        {selected ? (
          <View>
            <Text style={styles.customerName}>{selected.customerName}</Text>
            <View style={styles.detailsRow}>
              <View style={styles.detailCol}>
                <Text style={styles.detailLabel}>CÓDIGO</Text>
                <Text style={styles.detailValue}>{selected.hydrometer.code}</Text>
              </View>
              <View style={styles.detailCol}>
                <Text style={styles.detailLabel}>ÚLTIMA LEITURA</Text>
                <Text style={styles.detailValue}>
                  {formatMeterReading(selected.hydrometer.last_reading_value)} m³
                </Text>
              </View>
            </View>
            {!!selected.hydrometer.brand && (
              <Text style={styles.brandHint}>
                Marca/Modelo: {selected.hydrometer.brand} {selected.hydrometer.model || ''}
              </Text>
            )}
            {!!selected.hydrometer.location_description && (
              <Text style={styles.locationHint}>
                📍 Local: {selected.hydrometer.location_description}
              </Text>
            )}
            <TouchableOpacity
              style={[shared.btnSecondary, { marginTop: 14 }]}
              onPress={() => setModalVisible(true)}
            >
              <Text style={shared.btnSecondaryText}>Alterar hidrômetro</Text>
            </TouchableOpacity>
          </View>
        ) : (
          <View style={styles.emptySelector}>
            <Text style={styles.emptySelectorText}>Nenhum hidrômetro selecionado ainda.</Text>
            <TouchableOpacity style={shared.btnPrimary} onPress={() => setModalVisible(true)}>
              <Text style={shared.btnPrimaryText}>Selecionar Ponto da Rota</Text>
            </TouchableOpacity>
          </View>
        )}
      </View>

      {/* STEP 2: Capture Photo */}
      {selected && (
        <View style={shared.card}>
          <Text style={shared.sectionTitle}>2. Imagem de teste</Text>

          {photoUri ? (
            <View>
              <Image source={{ uri: photoUri }} style={styles.capturedImage} />
              <View style={styles.photoActions}>
                <TouchableOpacity style={shared.btnSecondary} onPress={handleOpenCamera}>
                  <Text style={shared.btnSecondaryText}>Refazer Captura</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[shared.btnSecondary, { borderColor: colors.danger }]} onPress={resetCapture}>
                  <Text style={[shared.btnSecondaryText, { color: colors.danger }]}>Remover Foto</Text>
                </TouchableOpacity>
              </View>
            </View>
          ) : (
            <TouchableOpacity style={styles.btnCapturePlaceholder} onPress={handleOpenCamera}>
              <Svg width={32} height={32} viewBox="0 0 24 24" fill="none" stroke={colors.cyan} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                <Path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
                <Circle cx="12" cy="13" r="4" />
              </Svg>
              <Text style={styles.btnCapturePlaceholderText}>Abrir Câmera de Teste</Text>
            </TouchableOpacity>
          )}
        </View>
      )}

      {/* STEP 3: Verdict and Quality Metrics */}
      {photoUri && selected && (
        <View>
          {verdictLoading ? (
            <View style={shared.card}>
              <ActivityIndicator size="large" color={colors.cyan} />
              <Text style={styles.loadingVerdictText}>Executando inteligência local...</Text>
            </View>
          ) : verdict ? (
            <View>
              {/* Verdict metrics card */}
              <View style={shared.card}>
                <Text style={shared.sectionTitle}>3. Análise da inferência local</Text>

                <View style={styles.predictionRow}>
                  <View style={{ flex: 1.2 }}>
                    <Text style={styles.predLabel}>LEITURA PREDITA</Text>
                    <Text style={styles.predValue}>
                      {verdict.predicted_value !== null
                        ? `${formatMeterReading(verdict.predicted_value)} m³`
                        : 'Falha no OCR'}
                    </Text>
                  </View>
                  <View style={{ flex: 0.8, alignItems: 'flex-end' }}>
                    <Text style={styles.predLabel}>CONFIANÇA</Text>
                    <View
                      style={[
                        styles.confidenceBadge,
                        {
                          backgroundColor:
                            (verdict.confidence ?? 0) >= 0.9
                              ? colors.successSoft
                              : (verdict.confidence ?? 0) >= 0.7
                                ? colors.warningSoft
                                : colors.dangerSoft,
                        },
                      ]}
                    >
                      <Text
                        style={[
                          styles.confidenceText,
                          {
                            color:
                              (verdict.confidence ?? 0) >= 0.9
                                ? colors.success
                                : (verdict.confidence ?? 0) >= 0.7
                                  ? colors.warning
                                  : colors.danger,
                          },
                        ]}
                      >
                        {verdict.confidence !== null
                          ? `${(verdict.confidence * 100).toFixed(1)}%`
                          : '0.0%'}
                      </Text>
                    </View>
                  </View>
                </View>

                {/* Quality Metrics */}
                {verdict.quality && (
                  <View style={styles.metricsContainer}>
                    <Text style={styles.metricsTitle}>Métricas de Qualidade da Imagem</Text>

                    <MetricProgress label="Foco / Nitidez (Blur)" val={verdict.quality.blur ?? 0} inverse />
                    <MetricProgress label="Reflexo / Brilho (Glare)" val={verdict.quality.glare ?? 0} inverse />
                    <MetricProgress label="Escuridão (Darkness)" val={verdict.quality.darkness ?? 0} inverse />
                    <MetricProgress label="Contraste Local" val={verdict.quality.contrast ?? 0} />

                    <View style={styles.usabilityRow}>
                      <Text style={styles.usabilityLabel}>Status da Foto:</Text>
                      <Text
                        style={[
                          styles.usabilityValue,
                          { color: verdict.quality.usable ? colors.success : colors.danger },
                        ]}
                      >
                        {verdict.quality.usable ? 'Usável' : 'Não Recomendada'}
                      </Text>
                    </View>

                    {verdict.quality.recapture_reason && (
                      <View style={styles.warningBox}>
                        <Text style={styles.warningBoxText}>
                          ⚠️ {verdict.quality.recapture_reason}
                        </Text>
                      </View>
                    )}
                  </View>
                )}

                {/* Shadow Model information */}
                {verdict.quality && (verdict.quality as any).glm_shadow && (
                  <View style={styles.shadowBox}>
                    <Text style={styles.shadowBoxTitle}>Resultado Shadow (GLM/Kimi)</Text>
                    <Text style={styles.shadowBoxText}>
                      Valor predito: {(verdict.quality as any).glm_shadow.predicted_value !== undefined ? `${(verdict.quality as any).glm_shadow.predicted_value} m³` : 'Falha'}
                    </Text>
                  </View>
                )}

                {/* Model Version */}
                <Text style={styles.modelVersionText}>
                  Modelo: {verdict.model_version} • {verdict.auto_fill_allowed ? 'Auto-preenchimento liberado' : 'Confirmação obrigatória'}
                </Text>
              </View>

              {/* Step 4: Ground Truth / Manual confirmation */}
              <View style={shared.card}>
                <Text style={shared.sectionTitle}>4. Verdade operacional (Gabarito)</Text>

                <Text style={shared.label}>Dígitos vermelhos do visor</Text>
                <View style={{ flexDirection: 'row', gap: 10, marginBottom: 14 }}>
                  <TouchableOpacity
                    style={[styles.redOpt, selectedRedDigits === 2 && styles.redOptActive]}
                    onPress={() => setSelectedRedDigits(2)}
                  >
                    <Text style={[styles.redOptText, selectedRedDigits === 2 && styles.redOptTextActive]}>2 vermelhos</Text>
                  </TouchableOpacity>
                  <TouchableOpacity
                    style={[styles.redOpt, selectedRedDigits === 3 && styles.redOptActive]}
                    onPress={() => setSelectedRedDigits(3)}
                  >
                    <Text style={[styles.redOptText, selectedRedDigits === 3 && styles.redOptTextActive]}>3 vermelhos</Text>
                  </TouchableOpacity>
                </View>

                <Text style={shared.label}>Valor Real no Visor (sem vírgula)</Text>
                <TextInput
                  style={[shared.input, styles.manualInput]}
                  value={manualValue}
                  onChangeText={setManualValue}
                  keyboardType="decimal-pad"
                  placeholder="Ex: 0013440"
                  placeholderTextColor={colors.textMuted}
                />
                <Text style={styles.manualFormatHint}>
                  Interpretado como {formatMeterReading(parsedManualValue)} m³ com {selectedRedDigits} dígitos vermelhos.
                </Text>

                {/* Submit Action */}
                {!testResult?.submitted ? (
                  <TouchableOpacity
                    style={[shared.btnPrimary, { backgroundColor: colors.cyan, marginTop: 20 }, (parsedManualValue === null || submittingFeedback) && { opacity: 0.5 }]}
                    onPress={submitFeedback}
                    disabled={parsedManualValue === null || submittingFeedback}
                  >
                    {submittingFeedback ? (
                      <ActivityIndicator color="#fff" />
                    ) : (
                      <>
                        <Svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">
                          <Path d="m5 12 5 5L20 7" />
                        </Svg>
                        <Text style={shared.btnPrimaryText}>Enviar Captura de Teste</Text>
                      </>
                    )}
                  </TouchableOpacity>
                ) : (
                  <View style={styles.resultBox}>
                    <View style={[styles.resultBadge, { backgroundColor: testResult.wasCorrect ? colors.successSoft : colors.dangerSoft }]}>
                      <Text style={[styles.resultBadgeText, { color: testResult.wasCorrect ? colors.success : colors.danger }]}>
                        {testResult.wasCorrect ? 'ACERTOU!' : 'DIVERGÊNCIA REGISTRADA'}
                      </Text>
                    </View>
                    <Text style={styles.resultDetails}>
                      Predição: {testResult.predicted.toFixed(3)} m³{'\n'}
                      Confirmado: {testResult.confirmed.toFixed(3)} m³{'\n'}
                      Diferença: {testResult.difference.toFixed(3)} m³
                    </Text>
                    <TouchableOpacity
                      style={[shared.btnPrimary, { marginTop: 14 }]}
                      onPress={resetCapture}
                    >
                      <Text style={shared.btnPrimaryText}>Testar Nova Captura</Text>
                    </TouchableOpacity>
                  </View>
                )}
              </View>
            </View>
          ) : (
            <View style={shared.card}>
              <Text style={{ color: colors.danger, textAlign: 'center' }}>Não foi possível computar a inferência para esta foto.</Text>
              <TouchableOpacity style={[shared.btnSecondary, { marginTop: 12 }]} onPress={resetCapture}>
                <Text style={shared.btnSecondaryText}>Limpar e tentar novamente</Text>
              </TouchableOpacity>
            </View>
          )}
        </View>
      )}

      {/* Selection Modal */}
      <Modal
        visible={modalVisible}
        animationType="slide"
        transparent
        onRequestClose={() => setModalVisible(false)}
      >
        <View style={styles.modalBackdrop}>
          <View style={styles.modalCard}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Selecionar Hidrômetro</Text>
              <TouchableOpacity onPress={() => setModalVisible(false)}>
                <Text style={styles.closeModalText}>Fechar</Text>
              </TouchableOpacity>
            </View>

            <TextInput
              style={styles.modalSearch}
              placeholder="Buscar por cliente ou código"
              placeholderTextColor={colors.textMuted}
              value={searchQuery}
              onChangeText={setSearchQuery}
            />

            {loadingList ? (
              <ActivityIndicator size="large" color={colors.cyan} style={{ marginVertical: 32 }} />
            ) : (
              <FlatList
                data={filteredHydrometers}
                keyExtractor={item => item.hydrometer.id}
                style={{ maxHeight: 350 }}
                renderItem={({ item }) => (
                  <TouchableOpacity
                    style={styles.modalItem}
                    onPress={() => {
                      setSelected(item);
                      setSelectedRedDigits(item.hydrometer.red_digits ?? 3);
                      setVerdict(null);
                      setTestResult(null);
                      setModalVisible(false);
                    }}
                  >
                    <Text style={styles.modalItemCust}>{item.customerName}</Text>
                    <Text style={styles.modalItemCode}>
                      Código: {item.hydrometer.code} • Última: {formatMeterReading(item.hydrometer.last_reading_value)} m³
                    </Text>
                  </TouchableOpacity>
                )}
                ListEmptyComponent={
                  <Text style={styles.modalEmptyText}>Nenhum ponto da rota encontrado.</Text>
                }
              />
            )}
          </View>
        </View>
      </Modal>
    </ScrollView>
  );
}

// Sub-component to show a metric value and a tiny bar chart
function MetricProgress({ label, val, inverse }: { label: string; val: number; inverse?: boolean }) {
  const percentage = Math.round(val * 100);
  const color = inverse
    ? val >= 0.72
      ? colors.danger
      : val >= 0.5
        ? colors.warning
        : colors.success
    : val >= 0.7
      ? colors.success
      : val >= 0.4
        ? colors.warning
        : colors.danger;

  return (
    <View style={styles.metricItem}>
      <View style={styles.metricRow}>
        <Text style={styles.metricLabel}>{label}</Text>
        <Text style={[styles.metricVal, { color }]}>{percentage}%</Text>
      </View>
      <View style={styles.progressBg}>
        <View style={[styles.progressFill, { width: `${percentage}%`, backgroundColor: color }]} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  backText: {
    color: colors.cyan,
    fontWeight: '800',
    fontSize: 14,
  },
  badgeDev: {
    backgroundColor: colors.cyan,
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 6,
  },
  badgeDevText: {
    color: '#fff',
    fontSize: 9,
    fontWeight: '900',
    letterSpacing: 0.5,
  },
  title: {
    fontSize: 24,
    fontWeight: '900',
    color: colors.textPrimary,
  },
  subtitle: {
    fontSize: 13,
    color: colors.textMuted,
    lineHeight: 18,
    marginTop: 4,
    marginBottom: 20,
  },
  customerName: {
    fontSize: 18,
    fontWeight: '800',
    color: colors.textPrimary,
  },
  detailsRow: {
    flexDirection: 'row',
    gap: 14,
    marginTop: 12,
  },
  detailCol: {
    flex: 1,
    backgroundColor: colors.navy700,
    padding: 10,
    borderRadius: 8,
  },
  detailLabel: {
    fontSize: 9,
    fontWeight: '700',
    color: colors.textMuted,
  },
  detailValue: {
    fontSize: 14,
    fontWeight: '800',
    color: colors.textPrimary,
    marginTop: 4,
  },
  brandHint: {
    fontSize: 12,
    color: colors.textSecondary,
    marginTop: 10,
    fontWeight: '600',
  },
  locationHint: {
    fontSize: 12,
    color: colors.textMuted,
    marginTop: 6,
  },
  emptySelector: {
    alignItems: 'center',
    paddingVertical: 14,
  },
  emptySelectorText: {
    color: colors.textMuted,
    fontSize: 13,
    marginBottom: 14,
  },
  capturedImage: {
    width: '100%',
    height: 180,
    borderRadius: 12,
    backgroundColor: colors.navy700,
  },
  photoActions: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    gap: 12,
    marginTop: 14,
  },
  btnCapturePlaceholder: {
    borderWidth: 2,
    borderStyle: 'dashed',
    borderColor: colors.border,
    borderRadius: 14,
    paddingVertical: 24,
    alignItems: 'center',
    justifyContent: 'center',
  },
  btnCapturePlaceholderText: {
    color: colors.cyan,
    fontSize: 14,
    fontWeight: '800',
    marginTop: 8,
  },
  loadingVerdictText: {
    marginTop: 12,
    color: colors.textMuted,
    textAlign: 'center',
    fontSize: 13,
  },
  predictionRow: {
    flexDirection: 'row',
    alignItems: 'center',
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    paddingBottom: 14,
    marginBottom: 14,
  },
  predLabel: {
    fontSize: 10,
    fontWeight: '700',
    color: colors.textMuted,
    letterSpacing: 0.5,
  },
  predValue: {
    fontSize: 22,
    fontWeight: '900',
    color: colors.textPrimary,
    marginTop: 4,
  },
  confidenceBadge: {
    paddingHorizontal: 10,
    paddingVertical: 6,
    borderRadius: 8,
    marginTop: 4,
  },
  confidenceText: {
    fontWeight: '900',
    fontSize: 14,
  },
  metricsContainer: {
    backgroundColor: colors.navy700,
    borderRadius: 10,
    padding: 12,
    marginBottom: 12,
  },
  metricsTitle: {
    fontSize: 12,
    fontWeight: '800',
    color: colors.textPrimary,
    marginBottom: 10,
  },
  metricItem: {
    marginBottom: 10,
  },
  metricRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  metricLabel: {
    fontSize: 11,
    color: colors.textSecondary,
    fontWeight: '600',
  },
  metricVal: {
    fontSize: 11,
    fontWeight: '700',
  },
  progressBg: {
    height: 6,
    backgroundColor: colors.navy600,
    borderRadius: 3,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    borderRadius: 3,
  },
  usabilityRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 6,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    paddingTop: 8,
  },
  usabilityLabel: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.textSecondary,
  },
  usabilityValue: {
    fontSize: 13,
    fontWeight: '900',
  },
  warningBox: {
    backgroundColor: colors.warningSoft,
    padding: 8,
    borderRadius: 6,
    marginTop: 10,
  },
  warningBoxText: {
    fontSize: 11,
    color: colors.warning,
    lineHeight: 16,
    fontWeight: '600',
  },
  shadowBox: {
    backgroundColor: colors.navy700,
    borderLeftWidth: 3,
    borderLeftColor: colors.textMuted,
    padding: 10,
    borderRadius: 6,
    marginBottom: 12,
  },
  shadowBoxTitle: {
    fontSize: 10,
    fontWeight: '800',
    color: colors.textMuted,
    textTransform: 'uppercase',
  },
  shadowBoxText: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.textPrimary,
    marginTop: 4,
  },
  modelVersionText: {
    fontSize: 10,
    color: colors.textMuted,
    textAlign: 'center',
    marginTop: 6,
  },
  redOpt: {
    flex: 1,
    borderRadius: 10,
    paddingVertical: 10,
    alignItems: 'center',
    backgroundColor: colors.navy700,
    borderWidth: 1,
    borderColor: colors.border,
  },
  redOptActive: {
    backgroundColor: colors.dangerSoft,
    borderColor: colors.danger,
  },
  redOptText: {
    color: colors.textSecondary,
    fontWeight: '700',
    fontSize: 12,
  },
  redOptTextActive: {
    color: colors.danger,
    fontWeight: '800',
  },
  manualInput: {
    fontSize: 22,
    fontWeight: '800',
    textAlign: 'center',
    marginTop: 4,
  },
  manualFormatHint: {
    color: colors.textMuted,
    fontSize: 11,
    marginTop: 6,
    textAlign: 'center',
  },
  resultBox: {
    marginTop: 18,
    paddingTop: 16,
    borderTopWidth: 1,
    borderTopColor: colors.border,
    alignItems: 'center',
  },
  resultBadge: {
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 18,
    marginBottom: 12,
  },
  resultBadgeText: {
    fontSize: 13,
    fontWeight: '900',
  },
  resultDetails: {
    color: colors.textSecondary,
    fontSize: 13,
    lineHeight: 20,
    textAlign: 'center',
    fontWeight: '600',
  },
  modalCard: {
    backgroundColor: colors.navy900,
    borderRadius: 16,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 18,
    maxHeight: '80%',
    marginBottom: 70,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 14,
  },
  closeModalText: {
    color: colors.textMuted,
    fontWeight: '700',
    fontSize: 13,
  },
  modalSearch: {
    backgroundColor: colors.abyss,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    color: colors.textPrimary,
    fontSize: 14,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginBottom: 12,
  },
  modalItem: {
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
  modalItemCust: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: '800',
  },
  modalItemCode: {
    color: colors.textMuted,
    fontSize: 12,
    marginTop: 3,
  },
  modalEmptyText: {
    color: colors.textMuted,
    textAlign: 'center',
    marginVertical: 20,
  },
  modalBackdrop: {
    flex: 1,
    backgroundColor: 'rgba(15,23,42,0.38)',
    justifyContent: 'flex-end',
    padding: 16,
  },
  modalTitle: {
    color: colors.textPrimary,
    fontSize: 20,
    fontWeight: '800',
  },
});
