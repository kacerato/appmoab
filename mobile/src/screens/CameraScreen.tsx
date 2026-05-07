import React, { useState, useRef } from 'react';
import {
  View, Text, TouchableOpacity, StyleSheet, Alert, ActivityIndicator,
} from 'react-native';
import { CameraView, useCameraPermissions } from 'expo-camera';
import * as Location from 'expo-location';
import { useNavigation, useRoute } from '@react-navigation/native';
import { colors } from '../styles/theme';

export default function CameraScreen() {
  const navigation = useNavigation<any>();
  const route = useRoute<any>();
  const { customerName, hydrometerCode, hydrometerId, lastReading } = route.params;

  const [permission, requestPermission] = useCameraPermissions();
  const [capturing, setCapturing] = useState(false);
  const cameraRef = useRef<any>(null);

  if (!permission) {
    return <View style={styles.container}><ActivityIndicator color={colors.accent} /></View>;
  }

  if (!permission.granted) {
    return (
      <View style={[styles.container, { justifyContent: 'center', alignItems: 'center', padding: 32 }]}>
        <Text style={{ color: colors.textPrimary, fontSize: 16, fontWeight: '700', marginBottom: 12, textAlign: 'center' }}>
          Permissão de câmera necessária
        </Text>
        <Text style={{ color: colors.textMuted, fontSize: 13, textAlign: 'center', marginBottom: 24 }}>
          Para capturar fotos dos hidrômetros, precisamos de acesso à câmera.
        </Text>
        <TouchableOpacity style={styles.btnCapture} onPress={requestPermission}>
          <Text style={{ color: '#fff', fontWeight: '700' }}>Permitir Câmera</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const capturePhoto = async () => {
    if (!cameraRef.current || capturing) return;
    setCapturing(true);

    try {
      // Captura foto
      const photo = await cameraRef.current.takePictureAsync({
        base64: true,
        quality: 0.8,
        exif: true,
      });

      // Captura GPS
      let location = null;
      try {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status === 'granted') {
          location = await Location.getCurrentPositionAsync({
            accuracy: Location.Accuracy.High,
          });
        }
      } catch (e) {
        console.warn('GPS indisponível:', e);
      }

      // Navega para tela de resultado OCR
      navigation.navigate('OCRResult', {
        photoBase64: photo.base64,
        photoUri: photo.uri,
        latitude: location?.coords.latitude || null,
        longitude: location?.coords.longitude || null,
        capturedAt: new Date().toISOString(),
        hydrometerId,
        hydrometerCode,
        customerName,
        lastReading,
      });
    } catch (err: any) {
      Alert.alert('Erro', err.message || 'Falha ao capturar foto');
    } finally {
      setCapturing(false);
    }
  };

  return (
    <View style={styles.container}>
      <CameraView style={styles.camera} ref={cameraRef} facing="back">
        {/* Overlay superior */}
        <View style={styles.overlayTop}>
          <TouchableOpacity onPress={() => navigation.goBack()}>
            <Text style={{ color: '#fff', fontSize: 16, fontWeight: '600' }}>← Voltar</Text>
          </TouchableOpacity>
          <View>
            <Text style={{ color: '#fff', fontSize: 14, fontWeight: '700' }}>{customerName}</Text>
            <Text style={{ color: 'rgba(255,255,255,0.7)', fontSize: 12 }}>{hydrometerCode}</Text>
          </View>
        </View>

        {/* Guia de enquadramento */}
        <View style={styles.guide}>
          <View style={styles.guideBox}>
            <View style={[styles.corner, styles.cornerTL]} />
            <View style={[styles.corner, styles.cornerTR]} />
            <View style={[styles.corner, styles.cornerBL]} />
            <View style={[styles.corner, styles.cornerBR]} />
          </View>
          <Text style={styles.guideText}>
            Enquadre o mostrador do hidrômetro
          </Text>
        </View>

        {/* Botão de captura */}
        <View style={styles.overlayBottom}>
          <View style={styles.infoRow}>
            <Text style={styles.infoLabel}>Última leitura</Text>
            <Text style={styles.infoValue}>{lastReading.toFixed(2)} m³</Text>
          </View>

          <TouchableOpacity
            style={[styles.btnCapture, capturing && { opacity: 0.5 }]}
            onPress={capturePhoto}
            disabled={capturing}
          >
            {capturing ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <View style={styles.captureInner} />
            )}
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
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 20,
    paddingTop: 56,
    paddingBottom: 12,
    backgroundColor: 'rgba(0,0,0,0.5)',
  },
  guide: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  guideBox: {
    width: 280,
    height: 180,
    position: 'relative',
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
    color: 'rgba(255,255,255,0.8)',
    fontSize: 13,
    marginTop: 16,
    textAlign: 'center',
  },
  overlayBottom: {
    paddingHorizontal: 20,
    paddingBottom: 40,
    paddingTop: 16,
    backgroundColor: 'rgba(0,0,0,0.6)',
    alignItems: 'center',
    gap: 16,
  },
  infoRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 8,
  },
  infoLabel: { color: 'rgba(255,255,255,0.6)', fontSize: 12 },
  infoValue: { color: colors.cyan, fontSize: 12, fontWeight: '700' },
  btnCapture: {
    width: 72,
    height: 72,
    borderRadius: 36,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 4,
    borderColor: 'rgba(255,255,255,0.3)',
  },
  captureInner: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: '#fff',
  },
});
