import React, { createContext, useContext, useEffect, useMemo, useState } from 'react';
import * as SecureStore from 'expo-secure-store';
import { applyColorMode, colors } from '../styles/theme';

type MobileThemeMode = 'light' | 'dark';

interface MobileThemeContextValue {
  mode: MobileThemeMode;
  setMode: (mode: MobileThemeMode) => Promise<void>;
}

const THEME_KEY = 'mobile_theme_mode';
const MobileThemeContext = createContext<MobileThemeContextValue | null>(null);

export function MobileThemeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<MobileThemeMode>('light');

  useEffect(() => {
    let mounted = true;
    SecureStore.getItemAsync(THEME_KEY)
      .then(value => {
        if (!mounted) return;
        const nextMode = value === 'dark' ? 'dark' : 'light';
        applyColorMode(nextMode);
        setModeState(nextMode);
      })
      .catch(() => undefined);
    return () => {
      mounted = false;
    };
  }, []);

  const setMode = async (nextMode: MobileThemeMode) => {
    applyColorMode(nextMode);
    setModeState(nextMode);
    await SecureStore.setItemAsync(THEME_KEY, nextMode);
  };

  const value = useMemo(() => ({ mode, setMode }), [mode]);

  return <MobileThemeContext.Provider value={value}>{children}</MobileThemeContext.Provider>;
}

export function useMobileTheme() {
  const context = useContext(MobileThemeContext);
  if (!context) {
    return {
      mode: 'light' as const,
      setMode: async () => undefined,
      colors,
    };
  }
  return { ...context, colors };
}
