import React, { useRef, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as Location from 'expo-location';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useFeedback } from '../lib/feedback';
import { api } from '../lib/api';
import { findCachedHydrometerByQr, matchesHydrometerQr, normalizeScannedQrValue } from '../lib/route-cache';
import { colors } from '../styles/theme';

const GPS_TARGET_ACCURACY_METERS = 25;
const GPS_MAX_WAIT_MS = 4200;

function withTimeout<T>(promise: Promise<T>, timeoutMs: number): Promise<T | null> {
  return Promise.race([
    promise,
    new Promise<null>(resolve => setTimeout(() => resolve(null), timeoutMs)),
  ]);
}

async function getBestLocationSample() {
  const { status } = await Location.requestForegroundPermissionsAsync();
  if (status !== 'granted') return null;

  const startedAt = Date.now();
  let bestLocation: Location.LocationObject | null = null;

  while (Date.now() - startedAt < GPS_MAX_WAIT_MS) {
    const remainingMs = Math.max(GPS_MAX_WAIT_MS - (Date.now() - startedAt), 600);
    const location = await withTimeout(
      Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Highest }),
      remainingMs,
    );
    if (!location) break;
    const currentAccuracy = location.coords.accuracy ?? Number.POSITIVE_INFINITY;
    const bestAccuracy = bestLocation?.coords.accuracy ?? Number.POSITIVE_INFINITY;
    if (!bestLocation || currentAccuracy < bestAccuracy) {
      bestLocation = location;
    }
    if (currentAccuracy <= GPS_TARGET_ACCURACY_METERS) break;
  }

  return bestLocation;
}

interface QrResolveResult {
  matched: boolean;
  hydrometer_id?: string | null;
  hydrometer_code?: string | null;
  customer_id?: string | null;
  customer_name?: string | null;
  last_reading_value?: number | null;
  last_reading_date?: string | null;
  red_digits?: number | null;
  black_digits?: number | null;
  brand?: string | null;
  model?: string | null;
  location_description?: string | null;
}

interface ReadingNavigationPayload {
  hydrometerId?: string | null;
  hydrometerCode?: string | null;
  customerName?: string | null;
  lastReading?: number | null;
  redDigits?: number | null;
  blackDigits?: number | null;
  hydrometerBrand?: string | null;
  hydrometerModel?: string | null;
  locationDescription?: string | null;
  isInstallation?: boolean;
}

export default function CameraScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const { showToast } = useFeedback();
  const {
    stage = 'code',
    expectedCustomerId,
    expectedCustomerName,
    expectedHydrometerId,
    expectedHydrometerCode,
    expectedQrCodeToken,
    lastReading = 0,
    redDigits = 3,
    blackDigits = null,
    hydrometerBrand = '',
    hydrometerModel = '',
    locationDescription = '',
    hydrometerId,
    hydrometerCode,
    customerName,
    isInstallation = false,
  } = route.params || {};

  const [permission, requestPermission] = useCameraPermissions();
  const [capturing, setCapturing] = useState(false);
  const [resolvingQr, setResolvingQr] = useState(false);
  const cameraRef = useRef<any>(null);
  const qrScanLockRef = useRef(false);
  const lastQrScanRef = useRef<{ value: string; at: number } | null>(null);

  const activeHydrometerId = hydrometerId || expectedHydrometerId;
  const activeHydrometerCode = hydrometerCode || expectedHydrometerCode;
  const activeCustomerName = customerName || expectedCustomerName;

  const navigateToReading = (payload: ReadingNavigationPayload) => {
    if (!payload.hydrometerId) {
      showToast('Hidrometro nao localizado', 'Nao foi possivel identificar o hidrometro deste QR.', 'error');
      return;
    }

    navigation.navigate('Camera', {
      stage: 'reading',
      hydrometerId: payload.hydrometerId,
      hydrometerCode: payload.hydrometerCode || '',
      customerName: payload.customerName || expectedCustomerName || 'Escaneamento manual',
      lastReading: payload.lastReading ?? 0,
      redDigits: payload.redDigits || 3,
      blackDigits: payload.blackDigits || null,
      hydrometerBrand: payload.hydrometerBrand || '',
      hydrometerModel: payload.hydrometerModel || '',
      locationDescription: payload.locationDescription || '',
      isInstallation: Boolean(payload.isInstallation),
    });
  };

  const handleQrScanned = async ({ data }: { data: string }) => {
    if (stage !== 'code' || resolvingQr || capturing || qrScanLockRef.current) return;
    const scannedValue = normalizeScannedQrValue(data);
    if (!scannedValue) return;

    const now = Date.now();
    const lastScan = lastQrScanRef.current;
    if (lastScan?.value === scannedValue && now - lastScan.at < 3500) return;
    lastQrScanRef.current = { value: scannedValue, at: now };

    qrScanLockRef.current = true;
    setResolvingQr(true);

    try {
      const expectedHydrometer = expectedHydrometerId
        ? { code: expectedHydrometerCode || '', qr_code_token: expectedQrCodeToken || null }
        : null;

      if (expectedHydrometer && matchesHydrometerQr(scannedValue, expectedHydrometer)) {
        navigateToReading({
          hydrometerId: expectedHydrometerId,
          hydrometerCode: expectedHydrometerCode,
          customerName: expectedCustomerName,
          lastReading,
          redDigits,
          blackDigits,
          hydrometerBrand,
          hydrometerModel,
          locationDescription,
          isInstallation,
        });
        return;
      }

      if (expectedHydrometer && expectedQrCodeToken) {
        showToast('QR fora da rota', 'Este QR pertence a outro hidrometro. Confira o cliente aberto antes de seguir.', 'error');
        return;
      }

      const cachedMatch = await findCachedHydrometerByQr(scannedValue);
      if (cachedMatch) {
        const { customer, hydrometer } = cachedMatch;
        navigateToReading({
          hydrometerId: hydrometer.id,
          hydrometerCode: hydrometer.code,
          customerName: customer.name,
          lastReading: hydrometer.last_reading_value ?? 0,
          redDigits: hydrometer.red_digits || 3,
          blackDigits: hydrometer.black_digits || null,
          hydrometerBrand: hydrometer.brand || '',
          hydrometerModel: hydrometer.model || '',
          locationDescription: hydrometer.location_description || '',
          isInstallation: !hydrometer.last_reading_date,
        });
        return;
      }

      const result = await api.post<QrResolveResult>('/hydrometers/resolve-qr', { qr_code_token: scannedValue });

      if (!result.matched || !result.hydrometer_id) {
        showToast('QR Code nao encontrado', 'Este QR nao esta vinculado a nenhum cliente ativo.', 'warning');
        return;
      }

      if (expectedHydrometerId && result.hydrometer_id !== expectedHydrometerId) {
        showToast('QR fora da rota', `O QR lido pertence a ${result.customer_name || 'outro cliente'}.`, 'error');
        return;
      }

      navigateToReading({
        hydrometerId: result.hydrometer_id,
        hydrometerCode: result.hydrometer_code,
        customerName: result.customer_name,
        lastReading: result.last_reading_value || 0,
        redDigits: result.red_digits || 3,
        blackDigits: result.black_digits || null,
        hydrometerBrand: result.brand || '',
        hydrometerModel: result.model || '',
        locationDescription: result.location_description || '',
        isInstallation: !result.last_reading_date,
      });
    } catch (error) {
      showToast('Falha ao ler QR Code', error instanceof Error ? error.message : 'Nao foi possivel validar o QR.', 'error');
    } finally {
      setResolvingQr(false);
      setTimeout(() => {
        qrScanLockRef.current = false;
      }, 700);
    }
  };

  if (!permission) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={styles.centered}>
          <ActivityIndicator color={colors.accent} />
        </View>
      </SafeAreaView>
    );
  }

  if (!permission.granted) {
    return (
      <SafeAreaView style={styles.container}>
        <View style={[styles.centered, styles.permissionPanel]}>
          <Text style={styles.permissionTitle}>Permissao de camera necessaria</Text>
          <Text style={styles.permissionText}>
            O colaborador precisa da camera para registrar o codigo do hidrometro e depois a medicao.
          </Text>
          <TouchableOpacity style={styles.btnPrimary} onPress={requestPermission}>
            <Text style={styles.btnPrimaryText}>Permitir camera</Text>
          </TouchableOpacity>
        </View>
      </SafeAreaView>
    );
  }

  const capturePhoto = async () => {
    if (!cameraRef.current || capturing) return;
    setCapturing(true);

    try {
      const photo = await cameraRef.current.takePictureAsync({
        base64: true,
        quality: 0.8,
      });
      const framesBase64: string[] = [];
      if (stage === 'reading' || stage === 'dev_test') {
        for (let index = 0; index < 2; index += 1) {
          try {
            const frame = await cameraRef.current.takePictureAsync({ base64: true, quality: 0.72, skipProcessing: true });
            if (frame?.base64) framesBase64.push(frame.base64);
          } catch {
            break;
          }
        }
      }

      if (stage === 'code') {
        navigation.navigate('ManualCode', {
          photoBase64: photo.base64,
          photoUri: photo.uri,
          expectedCustomerId,
          expectedCustomerName,
          expectedHydrometerId,
          expectedHydrometerCode,
          lastReading,
          redDigits,
          blackDigits,
          hydrometerBrand,
          hydrometerModel,
          locationDescription,
          isInstallation,
        });
        return;
      }

      if (stage === 'dev_test') {
        navigation.navigate('DevVisionTest', {
          photoBase64: photo.base64,
          photoUri: photo.uri,
          framesBase64,
          capturedAt: new Date().toISOString(),
          hydrometerId: activeHydrometerId,
          hydrometerCode: activeHydrometerCode,
          customerName: activeCustomerName,
          lastReading,
          redDigits,
          blackDigits,
          hydrometerBrand,
          hydrometerModel,
          locationDescription,
          isInstallation,
        });
        return;
      }

      let location = null;
      try {
        location = await getBestLocationSample();
      } catch (error) {
        console.warn('GPS indisponivel:', error);
      }

      navigation.navigate('OCRResult', {
        photoBase64: photo.base64,
        photoUri: photo.uri,
        framesBase64,
        latitude: location?.coords.latitude || null,
        longitude: location?.coords.longitude || null,
        locationAccuracyMeters: location?.coords.accuracy || null,
        capturedAt: new Date().toISOString(),
        hydrometerId: activeHydrometerId,
        hydrometerCode: activeHydrometerCode,
        customerName: activeCustomerName,
        lastReading,
        redDigits,
        blackDigits,
        hydrometerBrand,
        hydrometerModel,
        locationDescription,
        isInstallation,
      });
    } catch (error) {
      showToast(
        'Falha ao capturar foto',
        error instanceof Error ? error.message : 'Nao foi possivel capturar a imagem.',
        'error',
      );
    } finally {
      setCapturing(false);
    }
  };

  const stageTitle = stage === 'code'
    ? 'Etapa 1 - QR Code do cliente'
    : stage === 'dev_test'
      ? 'Modo Dev - Coleta de Teste'
      : isInstallation
        ? 'Etapa 2 - Instalacao do hidrometro'
        : 'Etapa 2 - Leitura do mostrador';
  const guideText = stage === 'code'
    ? 'Aponte para o QR Code impresso no ponto do cliente. Se precisar, toque para fotografar e digitar.'
    : stage === 'dev_test'
      ? 'Fotografe o visor do hidrometro para rodar o teste de visao e alimentar o dataset.'
      : isInstallation
        ? 'Fotografe o hidrometro instalado e informe o valor inicial do mostrador.'
        : 'Enquadre somente os numeros do mostrador para reduzir confusao no OCR.';

  return (
    <SafeAreaView style={styles.container} edges={['left', 'right']}>
      <View style={styles.cameraShell}>
        <CameraView
          style={styles.camera}
          ref={cameraRef}
          facing="back"
          onBarcodeScanned={stage === 'code' && !resolvingQr ? handleQrScanned : undefined}
          barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
        />

        <View pointerEvents="box-none" style={styles.overlay}>
          <View style={styles.overlayTop}>
            <TouchableOpacity onPress={() => navigation.goBack()}>
              <Text style={styles.backText}>Voltar</Text>
            </TouchableOpacity>
            <View style={styles.stageHeaderText}>
              <Text style={styles.stageTitle}>{stageTitle}</Text>
              <Text style={styles.stageSubtitle}>{activeCustomerName}</Text>
            </View>
          </View>

          <View style={styles.guide}>
            <View style={[styles.guideBox, stage === 'code' ? styles.guideCode : styles.guideReading]}>
              <View style={[styles.corner, styles.cornerTL]} />
              <View style={[styles.corner, styles.cornerTR]} />
              <View style={[styles.corner, styles.cornerBL]} />
              <View style={[styles.corner, styles.cornerBR]} />
            </View>
            <Text style={styles.guideText}>{guideText}</Text>
          </View>

          <View style={styles.overlayBottom}>
            <View style={styles.infoCard}>
              <Text style={styles.infoLabel}>{stage === 'code' ? 'QR esperado' : 'Formato do mostrador'}</Text>
              <Text style={styles.infoValue}>
                {stage === 'code'
                  ? activeHydrometerCode
                  : isInstallation
                    ? `${redDigits} vermelhos - instalacao`
                    : `${redDigits} vermelhos - base ${Number(lastReading || 0).toFixed(2)} m3`}
              </Text>
              {!!locationDescription && <Text style={styles.locationHint}>{locationDescription}</Text>}
            </View>

            <TouchableOpacity
              style={[styles.btnCapture, (capturing || resolvingQr) && { opacity: 0.5 }]}
              onPress={capturePhoto}
              disabled={capturing || resolvingQr}
            >
              {capturing || resolvingQr ? <ActivityIndicator color="#fff" /> : <View style={styles.captureInner} />}
            </TouchableOpacity>

            <Text style={styles.captureLabel}>
              {stage === 'code'
                ? 'QR automatico ou toque para digitar'
                : stage === 'dev_test'
                  ? 'Toque para testar visao'
                  : isInstallation
                    ? 'Toque para registrar instalacao'
                    : 'Toque para fotografar a leitura'}
            </Text>
          </View>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },
  cameraShell: { flex: 1, position: 'relative' },
  camera: { flex: 1 },
  overlay: {
    ...StyleSheet.absoluteFillObject,
    justifyContent: 'space-between',
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  permissionPanel: {
    padding: 32,
  },
  overlayTop: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 14,
    backgroundColor: 'rgba(0,0,0,0.46)',
  },
  backText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '800',
  },
  stageHeaderText: {
    flex: 1,
    marginLeft: 12,
  },
  stageTitle: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '800',
  },
  stageSubtitle: {
    color: 'rgba(255,255,255,0.72)',
    fontSize: 12,
    marginTop: 2,
  },
  guide: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  guideBox: {
    position: 'relative',
  },
  guideCode: {
    width: 240,
    height: 240,
  },
  guideReading: {
    width: 280,
    height: 180,
  },
  corner: {
    position: 'absolute',
    width: 30,
    height: 30,
    borderColor: colors.cyan,
    borderWidth: 3,
  },
  cornerTL: { top: 0, left: 0, borderRightWidth: 0, borderBottomWidth: 0 },
  cornerTR: { top: 0, right: 0, borderLeftWidth: 0, borderBottomWidth: 0 },
  cornerBL: { bottom: 0, left: 0, borderRightWidth: 0, borderTopWidth: 0 },
  cornerBR: { bottom: 0, right: 0, borderLeftWidth: 0, borderTopWidth: 0 },
  guideText: {
    color: 'rgba(255,255,255,0.84)',
    fontSize: 13,
    marginTop: 16,
    textAlign: 'center',
    maxWidth: 280,
    lineHeight: 18,
  },
  overlayBottom: {
    paddingHorizontal: 20,
    paddingBottom: 32,
    paddingTop: 16,
    backgroundColor: 'rgba(0,0,0,0.58)',
    alignItems: 'center',
    gap: 14,
  },
  infoCard: {
    backgroundColor: 'rgba(255,255,255,0.08)',
    borderRadius: 18,
    paddingVertical: 14,
    paddingHorizontal: 16,
    alignItems: 'center',
    minWidth: 240,
  },
  infoLabel: {
    color: 'rgba(255,255,255,0.6)',
    fontSize: 11,
    textTransform: 'uppercase',
    fontWeight: '700',
    marginBottom: 4,
  },
  infoValue: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '800',
  },
  locationHint: {
    color: colors.cyan,
    fontSize: 11,
    marginTop: 5,
    textAlign: 'center',
  },
  btnCapture: {
    width: 84,
    height: 84,
    borderRadius: 42,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 4,
    borderColor: 'rgba(255,255,255,0.28)',
  },
  captureInner: {
    width: 62,
    height: 62,
    borderRadius: 31,
    backgroundColor: '#fff',
  },
  captureLabel: {
    color: '#fff',
    fontSize: 12,
    fontWeight: '800',
    textTransform: 'uppercase',
    letterSpacing: 0.6,
  },
  permissionTitle: {
    color: colors.textPrimary,
    fontSize: 17,
    fontWeight: '800',
    marginBottom: 12,
    textAlign: 'center',
  },
  permissionText: {
    color: colors.textMuted,
    fontSize: 13,
    textAlign: 'center',
    marginBottom: 24,
    lineHeight: 19,
  },
  btnPrimary: {
    backgroundColor: colors.accent,
    borderRadius: 12,
    paddingHorizontal: 22,
    paddingVertical: 14,
  },
  btnPrimaryText: {
    color: '#fff',
    fontWeight: '800',
    fontSize: 14,
  },
});
