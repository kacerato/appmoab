import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, LayoutChangeEvent, Platform, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as FileSystem from 'expo-file-system/legacy';
import { manipulateAsync, SaveFormat } from 'expo-image-manipulator';
import * as Location from 'expo-location';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useIsFocused, useNavigation, useRoute } from '@react-navigation/native';
import { useFeedback } from '../lib/feedback';
import { api } from '../lib/api';
import { findCachedHydrometerByQr, matchesHydrometerQr, normalizeScannedQrValue } from '../lib/route-cache';
import { CameraRect, CameraSize, mapPreviewRectToPhotoCrop } from '../lib/camera-geometry';
import { colors } from '../styles/theme';

const GPS_TARGET_ACCURACY_METERS = 25;
const GPS_MAX_WAIT_MS = 4200;
const BURST_EXTRA_FRAMES = 4;
const BURST_INTERVAL_MS = 120;
const LIVE_VISION_INTERVAL_MS = 2800;
const LIVE_VISION_READY_INTERVAL_MS = 6500;
const LIVE_VISION_START_DELAY_MS = 900;

interface VisionQualityResult {
  usable: boolean;
  recapture_reason?: string | null;
  guidance_code?: string | null;
  blur?: number;
  glare?: number;
  darkness?: number;
  contrast?: number;
  perspective?: number;
  display_area_ratio?: number;
  display_found?: boolean;
  meter_found?: boolean;
}

interface CapturedFrame {
  uri: string;
  width: number;
  height: number;
  base64?: string;
}

interface PreparedFrame extends CapturedFrame {
  base64: string;
  crop?: {
    x: number;
    y: number;
    width: number;
    height: number;
  };
}

function createCaptureId() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, token => {
    const random = Math.floor(Math.random() * 16);
    const value = token === 'x' ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}

function selectPictureSize(sizes: string[], preview?: CameraSize | null) {
  const targetAspect = preview
    ? Math.min(preview.width, preview.height) / Math.max(preview.width, preview.height)
    : 9 / 16;
  const parsed = sizes
    .map(size => {
      const [width, height] = size.split('x').map(Number);
      const aspect = Math.min(width, height) / Math.max(width, height);
      return {
        size,
        width,
        height,
        pixels: width * height,
        aspectDelta: Math.abs(aspect - targetAspect),
      };
    })
    .filter(item => Number.isFinite(item.pixels) && item.pixels > 0 && item.pixels <= 8_500_000)
    .sort((left, right) => left.aspectDelta - right.aspectDelta || right.pixels - left.pixels);
  return parsed[0]?.size || sizes[0] || null;
}

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
  const isFocused = useIsFocused();
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
  const [cameraReady, setCameraReady] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [resolvingQr, setResolvingQr] = useState(false);
  const [qualityChecking, setQualityChecking] = useState(false);
  const [liveChecking, setLiveChecking] = useState(false);
  const [torchEnabled, setTorchEnabled] = useState(false);
  const [pictureSize, setPictureSize] = useState<string | null>(null);
  const [captureGuidance, setCaptureGuidance] = useState<string | null>(null);
  const [liveQuality, setLiveQuality] = useState<VisionQualityResult | null>(null);
  const [cameraLayout, setCameraLayout] = useState<CameraSize | null>(null);
  const [guideLayout, setGuideLayout] = useState<CameraRect | null>(null);
  const [guideBoxLayout, setGuideBoxLayout] = useState<CameraRect | null>(null);
  const cameraRef = useRef<any>(null);
  const qrScanLockRef = useRef(false);
  const lastQrScanRef = useRef<{ value: string; at: number } | null>(null);
  const captureBusyRef = useRef(false);
  const liveProbeBusyRef = useRef(false);

  const handleCameraReady = async () => {
    setCameraReady(true);
    if (pictureSize || !cameraRef.current?.getAvailablePictureSizesAsync) return;
    try {
      const sizes = await cameraRef.current.getAvailablePictureSizesAsync();
      setPictureSize(selectPictureSize(Array.isArray(sizes) ? sizes : [], cameraLayout));
    } catch {
      setPictureSize(null);
    }
  };

  const handleCameraLayout = (event: LayoutChangeEvent) => {
    const { width, height } = event.nativeEvent.layout;
    setCameraLayout({ width, height });
  };

  const handleGuideLayout = (event: LayoutChangeEvent) => {
    setGuideLayout(event.nativeEvent.layout);
  };

  const handleGuideBoxLayout = (event: LayoutChangeEvent) => {
    setGuideBoxLayout(event.nativeEvent.layout);
  };

  const prepareReadingFrame = useCallback(async (
    photo: CapturedFrame,
    compression: number,
  ): Promise<PreparedFrame> => {
    const guideRect = guideLayout && guideBoxLayout
      ? {
          x: guideLayout.x + guideBoxLayout.x,
          y: guideLayout.y + guideBoxLayout.y,
          width: guideBoxLayout.width,
          height: guideBoxLayout.height,
        }
      : null;
    const crop = cameraLayout && guideRect
      ? mapPreviewRectToPhotoCrop(
          cameraLayout,
          guideRect,
          { width: photo.width, height: photo.height },
        )
      : null;
    const result = await manipulateAsync(
      photo.uri,
      crop ? [{ crop: {
        originX: crop.originX,
        originY: crop.originY,
        width: crop.width,
        height: crop.height,
      } }] : [],
      {
        base64: true,
        compress: compression,
        format: SaveFormat.JPEG,
      },
    );
    if (!result.base64) {
      throw new Error('Não foi possível preparar o enquadramento da foto.');
    }
    return {
      uri: result.uri,
      width: result.width,
      height: result.height,
      base64: result.base64,
      crop: crop?.normalized,
    };
  }, [cameraLayout, guideBoxLayout, guideLayout]);

  useEffect(() => {
    if (!isFocused || stage === 'code' || !cameraReady || !cameraLayout || !guideLayout || !guideBoxLayout) {
      setLiveQuality(null);
      return undefined;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const schedule = (delay: number) => {
      timer = setTimeout(() => void probe(), delay);
    };
    const probe = async () => {
      let nextDelay = LIVE_VISION_INTERVAL_MS;
      const temporaryUris: string[] = [];
      if (cancelled) return;
      if (captureBusyRef.current || liveProbeBusyRef.current || !cameraRef.current) {
        schedule(500);
        return;
      }
      liveProbeBusyRef.current = true;
      setLiveChecking(true);
      try {
        const photo = await cameraRef.current.takePictureAsync({
          quality: 0.46,
          base64: false,
          shutterSound: false,
        });
        if (photo?.uri) temporaryUris.push(photo.uri);
        if (!photo?.uri || !photo?.width || !photo?.height) return;
        const prepared = await prepareReadingFrame(photo, 0.58);
        temporaryUris.push(prepared.uri);
        const quality = await api.post<VisionQualityResult>('/hydrometers/vision-quality', {
          photo_base64: prepared.base64,
          stage,
          red_digits: redDigits,
          black_digits: blackDigits || 4,
          capture_metadata: {
            capture_pipeline: 'mobile-live-guide-v3',
            guide_crop: prepared.crop || null,
          },
        }, 12000);
        if (!cancelled) {
          setLiveQuality(quality);
          if (quality.usable && quality.display_found !== false) {
            nextDelay = LIVE_VISION_READY_INTERVAL_MS;
          }
        }
      } catch {
        if (!cancelled) setLiveQuality(null);
      } finally {
        await Promise.all(
          [...new Set(temporaryUris)].map(uri => FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => undefined)),
        );
        liveProbeBusyRef.current = false;
        if (!cancelled) {
          setLiveChecking(false);
          schedule(nextDelay);
        }
      }
    };

    schedule(LIVE_VISION_START_DELAY_MS);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      liveProbeBusyRef.current = false;
    };
  }, [blackDigits, cameraLayout, cameraReady, guideBoxLayout, guideLayout, isFocused, prepareReadingFrame, redDigits, stage]);

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
    if (capturing || captureBusyRef.current) return;
    if (liveProbeBusyRef.current) {
      showToast('Visão analisando', 'Aguarde um instante para a câmera concluir a validação ao vivo.', 'warning');
      return;
    }
    if (!cameraRef.current || !cameraReady) {
      showToast('Câmera iniciando', 'Aguarde um instante e tente novamente.', 'warning');
      return;
    }
    captureBusyRef.current = true;
    setCapturing(true);
    setCaptureGuidance(null);

    try {
      const photo = await cameraRef.current.takePictureAsync({
        base64: stage === 'code',
        quality: stage === 'code' ? 0.90 : 1.0,
        shutterSound: true,
      });
      if (!photo?.uri || !photo?.width || !photo?.height || (stage === 'code' && !photo?.base64)) {
        throw new Error('A câmera não retornou a imagem. Tente novamente mantendo o aparelho firme.');
      }
      const preparedPhoto = stage === 'reading' || stage === 'dev_test'
        ? await prepareReadingFrame(photo, 0.94)
        : {
            uri: photo.uri,
            width: photo.width,
            height: photo.height,
            base64: photo.base64 as string,
            crop: undefined,
          };
      if ((stage === 'reading' || stage === 'dev_test') && photo.uri !== preparedPhoto.uri) {
        await FileSystem.deleteAsync(photo.uri, { idempotent: true }).catch(() => undefined);
      }
      const captureId = createCaptureId();
      const capturedAt = new Date().toISOString();
      const frameMetadata: Array<Record<string, unknown>> = [{
        index: 0,
        captured_at: capturedAt,
        width: preparedPhoto.width,
        height: preparedPhoto.height,
        source_width: photo.width,
        source_height: photo.height,
        guide_crop: preparedPhoto.crop || null,
        quality: 0.94,
        primary: true,
      }];

      if (stage === 'reading' || stage === 'dev_test') {
        setQualityChecking(true);
        let quality: VisionQualityResult;
        try {
          quality = await api.post<VisionQualityResult>('/hydrometers/vision-quality', {
            photo_base64: preparedPhoto.base64,
            stage,
            red_digits: redDigits,
            black_digits: blackDigits || 4,
            capture_metadata: {
              capture_pipeline: 'mobile-guided-crop-v3',
              guide_crop: preparedPhoto.crop || null,
            },
          }, 20000);
        } finally {
          setQualityChecking(false);
        }
        if (!quality.usable) {
          const message = quality.recapture_reason || 'A imagem não ficou segura para leitura. Refaça a captura.';
          setCaptureGuidance(message);
          showToast('Vamos melhorar esta foto', message, 'warning');
          return;
        }
      }

      const framesBase64: string[] = [];
      if (stage === 'reading' || stage === 'dev_test') {
        for (let index = 0; index < BURST_EXTRA_FRAMES; index += 1) {
          try {
            await new Promise(resolve => setTimeout(resolve, BURST_INTERVAL_MS));
            const frame = await cameraRef.current.takePictureAsync({
              base64: false,
              quality: 0.96,
              shutterSound: false,
            });
            if (frame?.uri && frame?.width && frame?.height) {
              let preparedFrame: PreparedFrame | null = null;
              try {
                preparedFrame = await prepareReadingFrame(frame, 0.90);
                framesBase64.push(preparedFrame.base64);
                frameMetadata.push({
                  index: index + 1,
                  captured_at: new Date().toISOString(),
                  width: preparedFrame.width,
                  height: preparedFrame.height,
                  source_width: frame.width,
                  source_height: frame.height,
                  guide_crop: preparedFrame.crop || null,
                  quality: 0.90,
                  primary: false,
                });
              } finally {
                await Promise.all(
                  [...new Set([frame.uri, preparedFrame?.uri].filter(Boolean) as string[])]
                    .map(uri => FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => undefined)),
                );
              }
            }
          } catch {
            break;
          }
        }
      }
      const captureMetadata = {
        capture_pipeline: 'mobile-burst-v2',
        platform: Platform.OS,
        picture_size: pictureSize,
        torch_enabled: torchEnabled,
        requested_frames: 1 + BURST_EXTRA_FRAMES,
        captured_frames: 1 + framesBase64.length,
        burst_interval_ms: BURST_INTERVAL_MS,
        framing_contract: 'preview-cover-to-sensor-crop-v1',
        guide_crop: preparedPhoto.crop || null,
      };

      if (stage === 'code') {
        navigation.navigate('ManualCode', {
          photoBase64: preparedPhoto.base64,
          photoUri: preparedPhoto.uri,
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
          photoBase64: preparedPhoto.base64,
          photoUri: preparedPhoto.uri,
          framesBase64,
          captureId,
          captureMetadata,
          frameMetadata,
          capturedAt,
          redDigits,
          blackDigits: 4,
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
        photoBase64: preparedPhoto.base64,
        photoUri: preparedPhoto.uri,
        framesBase64,
        captureId,
        captureMetadata,
        frameMetadata,
        latitude: location?.coords.latitude || null,
        longitude: location?.coords.longitude || null,
        locationAccuracyMeters: location?.coords.accuracy || null,
        capturedAt,
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
      captureBusyRef.current = false;
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
      ? 'Centralize a face do hidrometro e alinhe os roletes na faixa interna.'
      : isInstallation
        ? 'Centralize a face do hidrometro e alinhe os numeros na faixa interna.'
        : 'Centralize todo o mostrador; a faixa interna deve atravessar somente os numeros.';
  const liveReady = Boolean(
    liveQuality?.usable &&
    liveQuality.display_found !== false,
  );
  const liveStatusText = liveChecking
    ? 'Analisando hidrômetro e visor...'
    : liveReady
      ? liveQuality?.meter_found === false
        ? 'Visor pronto; mantenha a face centralizada'
        : 'Hidrômetro e visor prontos'
      : liveQuality?.recapture_reason || 'Aguardando hidrômetro no enquadramento';

  return (
    <SafeAreaView style={styles.container} edges={['left', 'right']}>
      <View style={styles.cameraShell} onLayout={handleCameraLayout}>
        <CameraView
          style={styles.camera}
          ref={cameraRef}
          facing="back"
          enableTorch={torchEnabled}
          animateShutter={false}
          pictureSize={pictureSize || undefined}
          onCameraReady={handleCameraReady}
          onMountError={event => {
            setCameraReady(false);
            showToast('Falha ao iniciar câmera', event.message || 'Não foi possível acessar a câmera.', 'error');
          }}
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

          <View style={styles.guide} onLayout={handleGuideLayout}>
            <View
              onLayout={handleGuideBoxLayout}
              style={[
                styles.guideBox,
                stage === 'code' ? styles.guideCode : styles.guideReading,
                stage !== 'code' && (liveReady ? styles.guideReady : styles.guideWaiting),
              ]}
            >
              {stage !== 'code' && (
                <>
                  <View style={styles.meterFaceGuide} />
                  <View style={styles.rollerGuide}>
                    {Array.from({ length: Math.max(3, Number(blackDigits || 4) + Number(redDigits || 3)) }).map((_, index) => (
                      <View key={index} style={styles.rollerSlot} />
                    ))}
                  </View>
                </>
              )}
              <View style={[styles.corner, styles.cornerTL]} />
              <View style={[styles.corner, styles.cornerTR]} />
              <View style={[styles.corner, styles.cornerBL]} />
              <View style={[styles.corner, styles.cornerBR]} />
            </View>
            <Text style={styles.guideText}>{guideText}</Text>
            {stage !== 'code' && (
              <View style={[styles.liveStatus, liveReady ? styles.liveStatusReady : styles.liveStatusWaiting]}>
                {liveChecking && <ActivityIndicator size="small" color={liveReady ? '#052e16' : '#111827'} />}
                <Text style={[styles.liveStatusText, liveReady && styles.liveStatusTextReady]} numberOfLines={2}>
                  {liveStatusText}
                </Text>
              </View>
            )}
            {!!captureGuidance && (
              <View style={styles.guidanceCard}>
                <Text style={styles.guidanceText}>{captureGuidance}</Text>
              </View>
            )}
          </View>

          <View style={styles.overlayBottom}>
            <View style={styles.infoCard}>
              <Text style={styles.infoLabel}>{stage === 'code' ? 'QR esperado' : 'Formato do mostrador'}</Text>
              <Text style={styles.infoValue}>
                {stage === 'code'
                  ? activeHydrometerCode
                  : stage === 'dev_test'
                    ? `${redDigits} vermelhos - teste livre`
                  : isInstallation
                    ? `${redDigits} vermelhos - instalacao`
                    : `${redDigits} vermelhos - base ${Number(lastReading || 0).toFixed(2)} m3`}
              </Text>
              {!!locationDescription && <Text style={styles.locationHint}>{locationDescription}</Text>}
            </View>

            <TouchableOpacity
              style={[styles.btnCapture, (capturing || resolvingQr || qualityChecking || !cameraReady) && { opacity: 0.5 }]}
              onPress={capturePhoto}
              disabled={capturing || resolvingQr || qualityChecking || !cameraReady}
            >
              {capturing || resolvingQr || qualityChecking || !cameraReady ? <ActivityIndicator color="#fff" /> : <View style={styles.captureInner} />}
            </TouchableOpacity>

            {stage !== 'code' && (
              <TouchableOpacity style={[styles.torchButton, torchEnabled && styles.torchButtonActive]} onPress={() => setTorchEnabled(value => !value)}>
                <Text style={styles.torchButtonText}>{torchEnabled ? 'Luz ligada' : 'Ligar luz'}</Text>
              </TouchableOpacity>
            )}

            <Text style={styles.captureLabel}>
              {qualityChecking
                ? 'Validando foco, reflexo e enquadramento'
                : liveChecking && !capturing
                  ? 'Visão ao vivo verificando o visor'
                : capturing && stage !== 'code'
                  ? 'Capturando sequência de evidências'
                  : stage === 'code'
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
    borderWidth: 1,
    borderRadius: 24,
  },
  guideCode: {
    width: 240,
    height: 240,
  },
  guideReading: {
    width: '84%',
    maxWidth: 330,
    aspectRatio: 1,
  },
  guideWaiting: {
    borderColor: 'rgba(245, 158, 11, 0.48)',
    backgroundColor: 'rgba(3, 7, 18, 0.06)',
  },
  guideReady: {
    borderColor: 'rgba(34, 197, 94, 0.92)',
    backgroundColor: 'rgba(34, 197, 94, 0.05)',
  },
  meterFaceGuide: {
    position: 'absolute',
    width: '82%',
    aspectRatio: 1,
    left: '9%',
    top: '9%',
    borderRadius: 999,
    borderWidth: 2,
    borderStyle: 'dashed',
    borderColor: 'rgba(255,255,255,0.52)',
  },
  rollerGuide: {
    position: 'absolute',
    left: '10%',
    right: '10%',
    top: '36%',
    height: '23%',
    borderWidth: 2,
    borderColor: colors.cyan,
    borderRadius: 8,
    backgroundColor: 'rgba(0,0,0,0.14)',
    flexDirection: 'row',
    padding: 3,
    gap: 2,
  },
  rollerSlot: {
    flex: 1,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.38)',
    borderRadius: 3,
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
  liveStatus: {
    marginTop: 12,
    maxWidth: 330,
    minHeight: 38,
    borderRadius: 999,
    paddingHorizontal: 14,
    paddingVertical: 9,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  liveStatusWaiting: {
    backgroundColor: 'rgba(245, 158, 11, 0.92)',
  },
  liveStatusReady: {
    backgroundColor: 'rgba(34, 197, 94, 0.94)',
  },
  liveStatusText: {
    color: '#111827',
    fontSize: 12,
    fontWeight: '900',
    textAlign: 'center',
    flexShrink: 1,
  },
  liveStatusTextReady: {
    color: '#052e16',
  },
  guidanceCard: {
    marginTop: 14,
    maxWidth: 320,
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderRadius: 14,
    backgroundColor: 'rgba(245, 158, 11, 0.94)',
  },
  guidanceText: {
    color: '#111827',
    fontSize: 13,
    fontWeight: '800',
    lineHeight: 18,
    textAlign: 'center',
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
  torchButton: {
    borderRadius: 999,
    paddingHorizontal: 16,
    paddingVertical: 9,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.28)',
    backgroundColor: 'rgba(255,255,255,0.08)',
  },
  torchButtonActive: {
    borderColor: colors.cyan,
    backgroundColor: 'rgba(34,211,238,0.18)',
  },
  torchButtonText: {
    color: '#fff',
    fontSize: 12,
    fontWeight: '800',
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
