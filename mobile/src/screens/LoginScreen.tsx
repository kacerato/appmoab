import React, { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useAuth } from '../lib/auth';
import { useMobileTheme } from '../lib/mobile-theme';
import { colors, shared } from '../styles/theme';

export default function LoginScreen() {
  const { login } = useAuth();
  const { mode } = useMobileTheme();
  const styles = useMemo(createStyles, [mode]);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleLogin = async () => {
    if (!email || !password) return;
    setError('');
    setLoading(true);
    try {
      await login(email, password);
    } catch (err: any) {
      setError(err.message || 'Erro ao fazer login');
    } finally {
      setLoading(false);
    }
  };

  return (
    <SafeAreaView style={styles.safeArea} edges={['top', 'left', 'right']}>
      <KeyboardAvoidingView
        style={styles.container}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <View style={styles.heroBackdrop}>
          <View style={styles.heroGlowPrimary} />
          <View style={styles.heroGlowSecondary} />
        </View>

        <View style={styles.inner}>
          <View style={styles.heroCard}>
            <View style={styles.logoIcon}>
              <Text style={styles.logoLetter}>A</Text>
            </View>
            <Text style={styles.eyebrow}>Operacao de campo</Text>
            <Text style={styles.logoTitle}>AquaMoab</Text>
            <Text style={styles.logoSub}>
              Entre para iniciar a rota, validar o hidrometro e registrar a leitura com revisao guiada.
            </Text>
          </View>

          <View style={styles.formCard}>
            <Text style={styles.formTitle}>Entrar no app do colaborador</Text>
            <Text style={styles.formSubtitle}>
              O acesso fica salvo neste aparelho para voce voltar direto para a rota.
            </Text>

            {error ? (
              <View style={styles.errorBox}>
                <Text style={styles.errorText}>{error}</Text>
              </View>
            ) : null}

            <View style={styles.fieldStack}>
              <View>
                <Text style={shared.label}>Email</Text>
                <TextInput
                  style={styles.input}
                  placeholder="seu@email.com"
                  placeholderTextColor={colors.textMuted}
                  value={email}
                  onChangeText={setEmail}
                  keyboardType="email-address"
                  autoCapitalize="none"
                  autoCorrect={false}
                />
              </View>

              <View>
                <Text style={shared.label}>Senha</Text>
                <TextInput
                  style={styles.input}
                  placeholder="Digite sua senha"
                  placeholderTextColor={colors.textMuted}
                  value={password}
                  onChangeText={setPassword}
                  secureTextEntry
                />
              </View>
            </View>

            <TouchableOpacity
              style={[styles.loginButton, loading && { opacity: 0.7 }]}
              onPress={handleLogin}
              disabled={loading}
            >
              {loading ? (
                <ActivityIndicator color="#fff" size="small" />
              ) : (
                <Text style={styles.loginButtonText}>Entrar e abrir minha rota</Text>
              )}
            </TouchableOpacity>
          </View>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function createStyles() {
  return StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: colors.navy950,
  },
  container: {
    flex: 1,
    backgroundColor: colors.navy950,
    justifyContent: 'center',
  },
  heroBackdrop: {
    ...StyleSheet.absoluteFillObject,
  },
  heroGlowPrimary: {
    position: 'absolute',
    top: 80,
    right: -20,
    width: 240,
    height: 240,
    borderRadius: 120,
    backgroundColor: 'rgba(29, 155, 240, 0.18)',
  },
  heroGlowSecondary: {
    position: 'absolute',
    bottom: 100,
    left: -40,
    width: 220,
    height: 220,
    borderRadius: 110,
    backgroundColor: 'rgba(83, 211, 247, 0.12)',
  },
  inner: {
    paddingHorizontal: 22,
    gap: 18,
  },
  heroCard: {
    backgroundColor: colors.sidebarNavy,
    borderRadius: 28,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 24,
  },
  logoIcon: {
    width: 72,
    height: 72,
    borderRadius: 22,
    backgroundColor: colors.accent,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 18,
  },
  logoLetter: {
    color: '#fff',
    fontSize: 32,
    fontWeight: '900',
  },
  eyebrow: {
    color: colors.cyan,
    fontSize: 11,
    fontWeight: '900',
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  logoTitle: {
    fontSize: 32,
    fontWeight: '900',
    color: colors.textPrimary,
    marginTop: 8,
  },
  logoSub: {
    fontSize: 14,
    color: colors.textSecondary,
    marginTop: 10,
    lineHeight: 21,
  },
  formCard: {
    backgroundColor: colors.navy800,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 22,
  },
  formTitle: {
    color: colors.textPrimary,
    fontSize: 20,
    fontWeight: '900',
  },
  formSubtitle: {
    color: colors.textMuted,
    fontSize: 13,
    lineHeight: 19,
    marginTop: 8,
    marginBottom: 18,
  },
  errorBox: {
    backgroundColor: 'rgba(255, 122, 122, 0.1)',
    borderRadius: 14,
    borderWidth: 1,
    borderColor: 'rgba(255, 122, 122, 0.25)',
    padding: 14,
    marginBottom: 16,
  },
  errorText: {
    color: colors.danger,
    fontSize: 13,
    lineHeight: 18,
    textAlign: 'center',
    fontWeight: '700',
  },
  fieldStack: {
    gap: 16,
  },
  input: {
    backgroundColor: colors.navy900,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 16,
    color: colors.textPrimary,
    fontSize: 15,
    paddingHorizontal: 16,
    paddingVertical: 15,
  },
  loginButton: {
    marginTop: 20,
    backgroundColor: colors.accent,
    borderRadius: 18,
    paddingVertical: 16,
    alignItems: 'center',
    justifyContent: 'center',
  },
  loginButtonText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '900',
  },
  });
}
