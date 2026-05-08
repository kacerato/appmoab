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
    top: 60,
    left: 16,
    right: 16,
    borderRadius: 18,
    paddingHorizontal: 18,
    paddingVertical: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 10 },
    shadowOpacity: 0.22,
    shadowRadius: 20,
    elevation: 10,
  },
  success: {
    backgroundColor: '#0E241C',
    borderWidth: 1,
    borderColor: 'rgba(54, 201, 142, 0.35)',
  },
  error: {
    backgroundColor: '#2A1417',
    borderWidth: 1,
    borderColor: 'rgba(255, 122, 122, 0.35)',
  },
  warning: {
    backgroundColor: '#2A2114',
    borderWidth: 1,
    borderColor: 'rgba(255, 184, 77, 0.35)',
  },
  info: {
    backgroundColor: '#101F30',
    borderWidth: 1,
    borderColor: 'rgba(83, 211, 247, 0.35)',
  },
  toastTitle: {
    color: '#F8FBFF',
    fontSize: 14,
    fontWeight: '900',
  },
  toastDescription: {
    color: '#C9D6E6',
    fontSize: 12,
    marginTop: 6,
    lineHeight: 18,
  },
});
