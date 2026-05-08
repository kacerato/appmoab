import React, { useRef, useState } from 'react';
import { ActivityIndicator, StyleSheet, Text, TouchableOpacity, View } from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as Location from 'expo-location';
import { useNavigation, useRoute } from '@react-navigation/native';
import { useFeedback } from '../lib/feedback';
import { colors } from '../styles/theme';

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
    lastReading = 0,
    locationDescription = '',
    hydrometerId,
    hydrometerCode,
    customerName,
  } = route.params || {};

  const [permission, requestPermission] = useCameraPermissions();
  const [capturing, setCapturing] = useState(false);
  const cameraRef = useRef<any>(null);

  const activeHydrometerId = hydrometerId || expectedHydrometerId;
  const activeHydrometerCode = hydrometerCode || expectedHydrometerCode;
  const activeCustomerName = customerName || expectedCustomerName;

  if (!permission) {
    return <View style={styles.container}><ActivityIndicator color={colors.accent} /></View>;
  }

  if (!permission.granted) {
    return (
      <View style={[styles.container, { justifyContent: 'center', alignItems: 'center', padding: 32 }]}>
        <Text style={styles.permissionTitle}>Permissão de câmera necessária</Text>
        <Text style={styles.permissionText}>
          Para registrar o código e a leitura do hidrômetro, o app precisa usar a câmera.
        </Text>
        <TouchableOpacity style={styles.btnPrimary} onPress={requestPermission}>
          <Text style={styles.btnPrimaryText}>Permitir câmera</Text>
        </TouchableOpacity>
      </View>
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

      if (stage === 'code') {
        navigation.navigate('HydrometerMatch', {
          photoBase64: photo.base64,
          photoUri: photo.uri,
          expectedCustomerId,
          expectedCustomerName,
          expectedHydrometerId,
          expectedHydrometerCode,
          lastReading,
          locationDescription,
        });
        return;
      }

      let location = null;
      try {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status === 'granted') {
          location = await Location.getCurrentPositionAsync({
            accuracy: Location.Accuracy.High,
          });
        }
      } catch (error) {
        console.warn('GPS indisponível:', error);
      }

      navigation.navigate('OCRResult', {
        photoBase64: photo.base64,
        photoUri: photo.uri,
        latitude: location?.coords.latitude || null,
        longitude: location?.coords.longitude || null,
        capturedAt: new Date().toISOString(),
        hydrometerId: activeHydrometerId,
        hydrometerCode: activeHydrometerCode,
        customerName: activeCustomerName,
        lastReading,
        locationDescription,
      });
    } catch (error) {
      showToast('Falha ao capturar foto', error instanceof Error ? error.message : 'Não foi possível capturar a imagem.', 'error');
    } finally {
      setCapturing(false);
    }
  };

  const stageTitle = stage === 'code' ? 'Etapa 1 · Código do hidrômetro' : 'Etapa 2 · Leitura do mostrador';
  const guideText = stage === 'code'
    ? 'Enquadre somente o código de identificação gravado no hidrômetro.'
    : 'Enquadre somente a leitura do mostrador para reduzir confusão no OCR.';

  return (
    <View style={styles.container}>
      <CameraView style={styles.camera} ref={cameraRef} facing="back">
        <View style={styles.overlayTop}>
          <TouchableOpacity onPress={() => navigation.goBack()}>
            <Text style={styles.backText}>← Voltar</Text>
          </TouchableOpacity>
          <View style={{ flex: 1, marginLeft: 12 }}>
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
            <Text style={styles.infoLabel}>{stage === 'code' ? 'Esperado na rota' : 'Leitura anterior'}</Text>
            <Text style={styles.infoValue}>{stage === 'code' ? activeHydrometerCode : `${lastReading.toFixed(2)} m³`}</Text>
            {!!locationDescription && (
              <Text style={styles.locationHint}>{locationDescription}</Text>
            )}
          </View>

          <TouchableOpacity
            style={[styles.btnCapture, capturing && { opacity: 0.5 }]}
            onPress={capturePhoto}
            disabled={capturing}
          >
            {capturing ? <ActivityIndicator color="#fff" /> : <View style={styles.captureInner} />}
          </TouchableOpacity>
        </View>
      </CameraView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#000' },
  camera: { flex: 1 },
  overlayTop: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 56,
    paddingBottom: 14,
    backgroundColor: 'rgba(0,0,0,0.46)',
  },
  backText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
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
    width: 300,
    height: 120,
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
    paddingBottom: 40,
    paddingTop: 16,
    backgroundColor: 'rgba(0,0,0,0.58)',
    alignItems: 'center',
    gap: 16,
  },
  infoCard: {
    backgroundColor: 'rgba(255,255,255,0.08)',
    borderRadius: 14,
    paddingVertical: 12,
    paddingHorizontal: 16,
    alignItems: 'center',
    minWidth: 230,
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
  },
  btnCapture: {
    width: 76,
    height: 76,
    borderRadius: 38,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 4,
    borderColor: 'rgba(255,255,255,0.28)',
  },
  captureInner: {
    width: 58,
    height: 58,
    borderRadius: 29,
    backgroundColor: '#fff',
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
