import React, { createContext, ReactNode, useCallback, useContext, useMemo, useState } from 'react';
import { Animated, StyleSheet, Text, View } from 'react-native';
import { colors } from '../styles/theme';

type ToastTone = 'success' | 'error' | 'warning' | 'info';

interface ToastState {
  visible: boolean;
  title: string;
  description?: string;
  tone: ToastTone;
}

interface FeedbackContextType {
  showToast: (title: string, description?: string, tone?: ToastTone) => void;
}

const FeedbackContext = createContext<FeedbackContextType | null>(null);

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<ToastState>({
    visible: false,
    title: '',
    description: '',
    tone: 'info',
  });
  const [fade] = useState(() => new Animated.Value(0));

  const showToast = useCallback((title: string, description?: string, tone: ToastTone = 'info') => {
    setToast({ visible: true, title, description, tone });
    fade.setValue(0);
    Animated.sequence([
      Animated.timing(fade, { toValue: 1, duration: 180, useNativeDriver: true }),
      Animated.delay(2600),
      Animated.timing(fade, { toValue: 0, duration: 180, useNativeDriver: true }),
    ]).start(() => {
      setToast(current => ({ ...current, visible: false }));
    });
  }, [fade]);

  const value = useMemo(() => ({ showToast }), [showToast]);

  return (
    <FeedbackContext.Provider value={value}>
      {children}
      {toast.visible && (
        <Animated.View
          pointerEvents="none"
          style={[
            styles.toast,
            styles[toast.tone],
            {
              opacity: fade,
              transform: [{
                translateY: fade.interpolate({
                  inputRange: [0, 1],
                  outputRange: [-18, 0],
                }),
              }],
            },
          ]}
        >
          <Text style={styles.toastTitle}>{toast.title}</Text>
          {toast.description ? <Text style={styles.toastDescription}>{toast.description}</Text> : null}
        </Animated.View>
      )}
    </FeedbackContext.Provider>
  );
}

export function useFeedback() {
  const context = useContext(FeedbackContext);
  if (!context) {
    throw new Error('useFeedback deve ser usado dentro de FeedbackProvider');
  }
  return context;
}

const styles = StyleSheet.create({
  toast: {
    position: 'absolute',
    top: 56,
    left: 16,
    right: 16,
    borderRadius: 14,
    paddingHorizontal: 16,
    paddingVertical: 14,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.12,
    shadowRadius: 14,
    elevation: 6,
  },
  success: {
    backgroundColor: '#ECFDF5',
    borderWidth: 1,
    borderColor: '#A7F3D0',
  },
  error: {
    backgroundColor: '#FEF2F2',
    borderWidth: 1,
    borderColor: '#FECACA',
  },
  warning: {
    backgroundColor: '#FFFBEB',
    borderWidth: 1,
    borderColor: '#FDE68A',
  },
  info: {
    backgroundColor: '#EFF6FF',
    borderWidth: 1,
    borderColor: '#BFDBFE',
  },
  toastTitle: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: '800',
  },
  toastDescription: {
    color: colors.textSecondary,
    fontSize: 12,
    marginTop: 4,
    lineHeight: 17,
  },
});
