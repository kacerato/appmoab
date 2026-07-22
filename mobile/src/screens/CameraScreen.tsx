import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ActivityIndicator, LayoutChangeEvent, Platform, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as FileSystem from 'expo-file-system/legacy';
import { manipulateAsync, SaveFormat, type Action } from 'expo-image-manipulator';
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
const LIVE_CACHE_LIMIT = 6;
const FINAL_SILENT_FRAMES = 2;
const TAP_BURST_EXTRA_FRAMES = 2;
const LIVE_CAPTURE_INTERVAL_MS = 320;
const LIVE_CAPTURE_BUSY_RETRY_MS = 220;
const LIVE_VISION_START_DELAY_MS = 250;
const LIVE_FRAME_MAX_AGE_MS = 15000;
const READING_FRAME_MAX_SIDE = 1800;
const LIVE_FRAME_MAX_SIDE = 1200;
const READING_CROP_PADDING_RATIO = 0.12;
const LIVE_DETECTION_HOLD_MS = 900;

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
  display_source?: string | null;
  display_bounds?: CameraRect | null;
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

interface CachedLiveFrame {
  base64: string;
  width: number;
  height: number;
  sourceWidth: number;
  sourceHeight: number;
  capturedAt: string;
  capturedAtMs: number;
  crop?: CameraRect;
  detectionScore?: number;
  detected?: boolean;
}

interface CachedLocationSample {
  value: Location.LocationObject;
  capturedAtMs: number;
}

function mapDetectedBoundsToGuide(bounds: CameraRect | null): CameraRect | null {
  if (!bounds || bounds.width <= 0 || bounds.height <= 0) return null;
  // O detector recebe um crop com folga ao redor do guia. Esta transformação
  // traz a caixa encontrada de volta para o espaço visual do guia sem exigir
  // que cada rolete coincida com uma caixa fixa.
  const expandedScale = 1 + READING_CROP_PADDING_RATIO * 2;
  const x = bounds.x * expandedScale - READING_CROP_PADDING_RATIO;
  const y = bounds.y * expandedScale - READING_CROP_PADDING_RATIO;
  const right = (bounds.x + bounds.width) * expandedScale - READING_CROP_PADDING_RATIO;
  const bottom = (bounds.y + bounds.height) * expandedScale - READING_CROP_PADDING_RATIO;
  const clampedX = Math.max(0, Math.min(1, x));
  const clampedY = Math.max(0, Math.min(1, y));
  return {
    x: clampedX,
    y: clampedY,
    width: Math.min(1 - clampedX, Math.max(0.04, right - clampedX)),
    height: Math.min(1 - clampedY, Math.max(0.04, bottom - clampedY)),
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
    // O pipeline reduz a imagem antes do OCR. Capturar 8 MP apenas trava o
    // sensor e aumenta JPEG/base64 sem acrescentar detalhe útil aos roletes.
    .filter(item => Number.isFinite(item.pixels) && item.pixels > 0 && item.pixels <= 5_000_000)
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
  const [liveChecking, setLiveChecking] = useState(false);
  const [torchEnabled, setTorchEnabled] = useState(false);
  const [pictureSize, setPictureSize] = useState<string | null>(null);
  const [liveQuality, setLiveQuality] = useState<VisionQualityResult | null>(null);
  const [liveMeterDetected, setLiveMeterDetected] = useState(false);
  const [liveDisplayBounds, setLiveDisplayBounds] = useState<CameraRect | null>(null);
  const [cameraLayout, setCameraLayout] = useState<CameraSize | null>(null);
  const [guideLayout, setGuideLayout] = useState<CameraRect | null>(null);
  const [guideBoxLayout, setGuideBoxLayout] = useState<CameraRect | null>(null);
  const cameraRef = useRef<any>(null);
  const qrScanLockRef = useRef(false);
  const lastQrScanRef = useRef<{ value: string; at: number } | null>(null);
  const captureBusyRef = useRef(false);
  const liveProbeBusyRef = useRef(false);
  const livePresenceBusyRef = useRef(false);
  const liveDetectionUntilRef = useRef(0);
  const pendingPresenceFrameRef = useRef<{ prepared: PreparedFrame; cachedFrame: CachedLiveFrame } | null>(null);
  const liveCameraCaptureRef = useRef<Promise<void> | null>(null);
  const liveFrameCacheRef = useRef<CachedLiveFrame[]>([]);
  const locationSampleRef = useRef<CachedLocationSample | null>(null);
  const locationPromiseRef = useRef<Promise<Location.LocationObject | null> | null>(null);

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
    maximumSide = READING_FRAME_MAX_SIDE,
    cropToGuide = false,
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
          READING_CROP_PADDING_RATIO,
        )
      : null;
    const workingWidth = cropToGuide && crop ? crop.width : photo.width;
    const workingHeight = cropToGuide && crop ? crop.height : photo.height;
    const actions: Action[] = cropToGuide && crop
      ? [{
          crop: {
            originX: crop.originX,
            originY: crop.originY,
            width: crop.width,
            height: crop.height,
          },
        }]
      : [];
    if (Math.max(workingWidth, workingHeight) > maximumSide) {
      actions.push({
        resize: workingWidth >= workingHeight
          ? { width: maximumSide }
          : { height: maximumSide },
      });
    }
    const result = await manipulateAsync(
      photo.uri,
      actions,
      {
        base64: true,
        compress: compression,
        format: SaveFormat.JPEG,
      },
    );
    if (!result.base64) {
      throw new Error('Não foi possível preparar a foto do hidrômetro.');
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
    if (!isFocused || stage === 'code') return undefined;
    let cancelled = false;
    const pending = getBestLocationSample();
    locationPromiseRef.current = pending;
    void pending
      .then(value => {
        if (!cancelled && value) {
          locationSampleRef.current = { value, capturedAtMs: Date.now() };
        }
      })
      .finally(() => {
        if (locationPromiseRef.current === pending) locationPromiseRef.current = null;
      });
    return () => {
      cancelled = true;
    };
  }, [isFocused, stage]);

  useEffect(() => {
    if (!isFocused || stage === 'code' || !cameraReady || !cameraLayout || !guideLayout || !guideBoxLayout) {
      setLiveQuality(null);
      setLiveMeterDetected(false);
      setLiveDisplayBounds(null);
      liveDetectionUntilRef.current = 0;
      pendingPresenceFrameRef.current = null;
      liveFrameCacheRef.current = [];
      return undefined;
    }

    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const schedule = (delay: number) => {
      timer = setTimeout(() => void probe(), delay);
    };

    const inspectPreparedFrame = (prepared: PreparedFrame, cachedFrame: CachedLiveFrame) => {
      if (livePresenceBusyRef.current) {
        // A rede nunca faz o live perder o quadro mais novo: substituímos o
        // pendente anterior e analisamos este assim que a resposta atual chegar.
        pendingPresenceFrameRef.current = { prepared, cachedFrame };
        return;
      }
      livePresenceBusyRef.current = true;
      setLiveChecking(true);
      void api.post<VisionQualityResult>('/hydrometers/vision-presence', {
        photo_base64: prepared.base64,
        stage,
        red_digits: redDigits,
        black_digits: blackDigits || 4,
        capture_metadata: {
          capture_pipeline: 'mobile-live-guide-v7-presence-only',
          guide_crop: prepared.crop || null,
        },
      }, 5000)
        .then(quality => {
          if (cancelled) return;
          const now = Date.now();
          const bounds = quality.display_bounds;
          const boundsAspect = bounds ? bounds.width / Math.max(bounds.height, 0.001) : 0;
          const reliableSource = quality.display_source === 'detector_onnx'
            || quality.display_source === 'red_roller_anchor';
          // O live só desenha a caixa quando localizou a faixa numérica por
          // uma âncora específica. Encontrar apenas a face do hidrômetro ou um
          // retângulo genérico nunca deixa o quadro verde nem decide a foto.
          const detected = Boolean(
            quality.display_found
            && reliableSource
            && bounds
            && bounds.width >= 0.18
            && bounds.height >= 0.025
            && boundsAspect >= 1.8
            && boundsAspect <= 12
            && Number(quality.display_area_ratio || 0) >= 0.006,
          );
          const detectionScore = (
            (quality.display_found ? 4 : 0)
            + (quality.meter_found ? 2 : 0)
            + (quality.usable ? 1 : 0)
            + Math.min(Number(quality.display_area_ratio || 0) * 8, 1)
            + Math.max(0, 1 - Number(quality.blur ?? 1))
            + Math.max(0, 1 - Number(quality.glare ?? 1)) * 0.5
          );
          liveFrameCacheRef.current = liveFrameCacheRef.current.map(frame => (
            frame.capturedAtMs === cachedFrame.capturedAtMs
              ? { ...frame, detected, detectionScore }
              : frame
          ));
          if (detected) {
            liveDetectionUntilRef.current = now + LIVE_DETECTION_HOLD_MS;
            setLiveMeterDetected(true);
            setLiveDisplayBounds(bounds || null);
          } else if (now >= liveDetectionUntilRef.current) {
            setLiveMeterDetected(false);
            setLiveDisplayBounds(null);
          }
          setLiveQuality(current => ({ ...current, ...quality }));
        })
        .catch(() => {
          if (!cancelled && Date.now() >= liveDetectionUntilRef.current) {
            setLiveMeterDetected(false);
          }
        })
        .finally(() => {
          livePresenceBusyRef.current = false;
          const pendingFrame = pendingPresenceFrameRef.current;
          pendingPresenceFrameRef.current = null;
          if (!cancelled && pendingFrame && !captureBusyRef.current) {
            inspectPreparedFrame(pendingFrame.prepared, pendingFrame.cachedFrame);
          } else if (!cancelled) {
            setLiveChecking(false);
          }
        });
    };

    const probe = async () => {
      const temporaryUris: string[] = [];
      if (cancelled) return;
      if (captureBusyRef.current || liveProbeBusyRef.current || !cameraRef.current) {
        schedule(LIVE_CAPTURE_BUSY_RETRY_MS);
        return;
      }
      liveProbeBusyRef.current = true;
      try {
        let photo: CapturedFrame;
        const capturePromise = cameraRef.current.takePictureAsync({
          quality: 0.46,
          base64: false,
          shutterSound: false,
        });
        const cameraHandoff = capturePromise.then(() => undefined, () => undefined);
        liveCameraCaptureRef.current = cameraHandoff;
        try {
          photo = await capturePromise;
        } finally {
          // A análise da API pode continuar, mas a câmera física já está livre
          // para o toque do operador. Não bloqueamos a captura durante a rede.
          if (liveCameraCaptureRef.current === cameraHandoff) {
            liveCameraCaptureRef.current = null;
          }
        }
        if (photo?.uri) temporaryUris.push(photo.uri);
        if (!photo?.uri || !photo?.width || !photo?.height) return;
        const prepared = await prepareReadingFrame(photo, 0.56, LIVE_FRAME_MAX_SIDE, true);
        temporaryUris.push(prepared.uri);
        const capturedAtMs = Date.now();
        const cachedFrame: CachedLiveFrame = {
          base64: prepared.base64,
          width: prepared.width,
          height: prepared.height,
          sourceWidth: photo.width,
          sourceHeight: photo.height,
          capturedAt: new Date(capturedAtMs).toISOString(),
          capturedAtMs,
          crop: prepared.crop,
        };
        liveFrameCacheRef.current = [
          ...liveFrameCacheRef.current.filter(item => capturedAtMs - item.capturedAtMs <= LIVE_FRAME_MAX_AGE_MS),
          cachedFrame,
        ].slice(-LIVE_CACHE_LIMIT);
        inspectPreparedFrame(prepared, cachedFrame);
      } catch {
        // O preview continua tentando; falha de um quadro não bloqueia o toque.
      } finally {
        await Promise.all(
          [...new Set(temporaryUris)].map(uri => FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => undefined)),
        );
        liveProbeBusyRef.current = false;
        if (!cancelled) schedule(LIVE_CAPTURE_INTERVAL_MS);
      }
    };

    schedule(LIVE_VISION_START_DELAY_MS);
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      pendingPresenceFrameRef.current = null;
      liveProbeBusyRef.current = false;
      livePresenceBusyRef.current = false;
      liveFrameCacheRef.current = [];
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
    if (!cameraRef.current || !cameraReady) {
      showToast('Câmera iniciando', 'Aguarde um instante e tente novamente.', 'warning');
      return;
    }
    captureBusyRef.current = true;
    setCapturing(true);

    try {
      // Se o toque coincidiu com o exato instante da foto silenciosa usada no
      // preview, aguardamos apenas a câmera física ser liberada. A chamada de
      // qualidade em rede nunca impede o operador de fotografar.
      const liveCameraCapture = liveCameraCaptureRef.current;
      if (liveCameraCapture) await liveCameraCapture;

      const photo = await cameraRef.current.takePictureAsync({
        base64: stage === 'code',
        quality: 0.90,
        shutterSound: true,
      });
      if (!photo?.uri || !photo?.width || !photo?.height || (stage === 'code' && !photo?.base64)) {
        throw new Error('A câmera não retornou a imagem. Tente novamente mantendo o aparelho firme.');
      }
      const preparedPhoto = stage === 'reading' || stage === 'dev_test'
        ? await prepareReadingFrame(photo, 0.90)
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
      const tapBurstFrames: CachedLiveFrame[] = [];
      if (stage === 'reading' || stage === 'dev_test') {
        for (let index = 0; index < TAP_BURST_EXTRA_FRAMES; index += 1) {
          let extraPhoto: CapturedFrame | null = null;
          let extraPrepared: PreparedFrame | null = null;
          try {
            extraPhoto = await cameraRef.current.takePictureAsync({
              base64: false,
              quality: 0.78,
              shutterSound: false,
            });
            if (!extraPhoto?.uri || !extraPhoto.width || !extraPhoto.height) continue;
            extraPrepared = await prepareReadingFrame(extraPhoto, 0.82);
            const capturedAtMs = Date.now();
            tapBurstFrames.push({
              base64: extraPrepared.base64,
              width: extraPrepared.width,
              height: extraPrepared.height,
              sourceWidth: extraPhoto.width,
              sourceHeight: extraPhoto.height,
              capturedAt: new Date(capturedAtMs).toISOString(),
              capturedAtMs,
              crop: extraPrepared.crop,
            });
          } catch {
            // Um quadro perdido não cancela o restante da sequência.
          } finally {
            const disposableUris = [extraPhoto?.uri, extraPrepared?.uri]
              .filter((uri): uri is string => Boolean(uri));
            await Promise.all(
              [...new Set(disposableUris)].map(uri => (
                FileSystem.deleteAsync(uri, { idempotent: true }).catch(() => undefined)
              )),
            );
          }
        }
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
        quality: 0.90,
        primary: true,
      }];

      const preflightQuality = stage === 'reading' || stage === 'dev_test'
        ? liveQuality
        : null;
      const cachedLiveFrames = (() => {
        if (stage !== 'reading' && stage !== 'dev_test') return [];
        const now = Date.now();
        return liveFrameCacheRef.current
          .filter(frame => now - frame.capturedAtMs <= LIVE_FRAME_MAX_AGE_MS)
          .sort((left, right) => (
            Number(Boolean(right.detected)) - Number(Boolean(left.detected))
            || Number(right.detectionScore || 0) - Number(left.detectionScore || 0)
            || right.capturedAtMs - left.capturedAtMs
          ))
          .slice(0, FINAL_SILENT_FRAMES)
          .sort((left, right) => left.capturedAtMs - right.capturedAtMs);
      })();
      liveFrameCacheRef.current = [];
      const framesBase64: string[] = [
        ...tapBurstFrames.map(item => item.base64),
        ...cachedLiveFrames.map(item => item.base64),
      ];
      tapBurstFrames.forEach((frame, index) => {
        frameMetadata.push({
          index: index + 1,
          captured_at: frame.capturedAt,
          width: frame.width,
          height: frame.height,
          source_width: frame.sourceWidth,
          source_height: frame.sourceHeight,
          guide_crop: frame.crop || null,
          quality: 0.82,
          primary: false,
          source: 'tap_burst',
        });
      });
      cachedLiveFrames.forEach((frame, index) => {
        frameMetadata.push({
          index: index + 1 + tapBurstFrames.length,
          captured_at: frame.capturedAt,
          width: frame.width,
          height: frame.height,
          source_width: frame.sourceWidth,
          source_height: frame.sourceHeight,
          guide_crop: frame.crop || null,
          quality: 0.58,
          primary: false,
          source: 'live_preview_cache',
        });
      });
      const captureMetadata = {
        capture_pipeline: 'mobile-burst-v7-manual-tap-with-live-evidence',
        platform: Platform.OS,
        picture_size: pictureSize,
        torch_enabled: torchEnabled,
        requested_frames: 1 + TAP_BURST_EXTRA_FRAMES + FINAL_SILENT_FRAMES,
        captured_frames: 1 + framesBase64.length,
        live_capture_interval_ms: LIVE_CAPTURE_INTERVAL_MS,
        framing_contract: 'full-click-frames-with-focused-live-evidence-v4',
        guide_crop: preparedPhoto.crop || null,
        reused_live_frames: cachedLiveFrames.length,
        tap_burst_frames: tapBurstFrames.length,
        live_detector_confirmed: liveMeterDetected,
        quality_advisory: preflightQuality ? {
          usable: preflightQuality.usable,
          guidance_code: preflightQuality.guidance_code || null,
          display_found: preflightQuality.display_found ?? null,
          meter_found: preflightQuality.meter_found ?? null,
          display_area_ratio: preflightQuality.display_area_ratio ?? null,
        } : null,
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

      const cachedLocation = locationSampleRef.current;
      let location = cachedLocation && Date.now() - cachedLocation.capturedAtMs <= 30_000
        ? cachedLocation.value
        : null;
      if (!location) {
        try {
          // O GPS já começou durante o enquadramento. No toque, damos apenas
          // uma pequena janela para a amostra em andamento terminar.
          location = await withTimeout(
            locationPromiseRef.current || getBestLocationSample(),
            350,
          );
        } catch (error) {
          console.warn('GPS indisponivel:', error);
        }
      }

      navigation.navigate('OCRResult', {
        autoSubmit: true,
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
        ? 'Centralize a face do hidrômetro. A faixa é apenas uma zona ampla; não precisa encaixar cada número.'
        : 'Centralize o mostrador. A faixa indica apenas a região provável dos números, sem exigir encaixe exato.';
  const liveReady = liveMeterDetected;
  const liveDisplayGuideBounds = mapDetectedBoundsToGuide(liveDisplayBounds);
  const liveStatusText = liveMeterDetected
        ? 'Visor localizado • guardando os melhores quadros silenciosos'
        : liveQuality?.meter_found
          ? 'Hidrômetro localizado • procurando exatamente a faixa dos números'
        : liveQuality?.recapture_reason
          ? 'Ainda procurando o hidrômetro; você pode fotografar mesmo assim.'
          : liveChecking
            ? 'Capturando hidrômetro, visor e números ao vivo...'
            : 'Captura contínua ativa; aponte para o hidrômetro';

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
                    <Text style={styles.rollerGuideLabel}>ZONA DOS NÚMEROS</Text>
                  </View>
                  {liveMeterDetected && liveDisplayGuideBounds && (
                    <View
                      pointerEvents="none"
                      style={[
                        styles.liveDigitsTracker,
                        {
                          left: `${liveDisplayGuideBounds.x * 100}%`,
                          top: `${liveDisplayGuideBounds.y * 100}%`,
                          width: `${liveDisplayGuideBounds.width * 100}%`,
                          height: `${liveDisplayGuideBounds.height * 100}%`,
                        },
                      ]}
                    >
                      <Text style={styles.liveDigitsTrackerLabel}>VISOR DETECTADO</Text>
                    </View>
                  )}
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
              style={[styles.btnCapture, (capturing || resolvingQr || !cameraReady) && { opacity: 0.5 }]}
              onPress={capturePhoto}
              disabled={capturing || resolvingQr || !cameraReady}
            >
              {capturing || resolvingQr || !cameraReady ? <ActivityIndicator color="#fff" /> : <View style={styles.captureInner} />}
            </TouchableOpacity>

            {stage !== 'code' && (
              <TouchableOpacity style={[styles.torchButton, torchEnabled && styles.torchButtonActive]} onPress={() => setTorchEnabled(value => !value)}>
                <Text style={styles.torchButtonText}>{torchEnabled ? 'Luz ligada' : 'Ligar luz'}</Text>
              </TouchableOpacity>
            )}

            <Text style={styles.captureLabel}>
              {capturing && stage !== 'code'
                  ? 'Capturando sequência de evidências'
                  : stage === 'code'
                ? 'QR automatico ou toque para digitar'
                : 'Captura ao vivo ativa • toque quando quiser'}
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
    justifyContent: 'flex-end',
    alignItems: 'center',
    paddingBottom: 3,
  },
  rollerGuideLabel: {
    color: 'rgba(255,255,255,0.82)',
    fontSize: 8,
    fontWeight: '900',
    letterSpacing: 1.1,
  },
  liveDigitsTracker: {
    position: 'absolute',
    minWidth: 44,
    minHeight: 22,
    borderWidth: 2,
    borderColor: '#22c55e',
    borderRadius: 7,
    backgroundColor: 'rgba(34,197,94,0.10)',
    justifyContent: 'flex-start',
    alignItems: 'flex-start',
  },
  liveDigitsTrackerLabel: {
    color: '#052e16',
    backgroundColor: '#86efac',
    fontSize: 7,
    fontWeight: '900',
    paddingHorizontal: 4,
    paddingVertical: 2,
    borderBottomRightRadius: 5,
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
