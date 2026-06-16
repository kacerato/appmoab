import React, { useEffect } from 'react';
import { ActivityIndicator, AppState, AppStateStatus, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import * as NavigationBar from 'expo-navigation-bar';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { AuthProvider, useAuth } from './src/lib/auth';
import { FeedbackProvider } from './src/lib/feedback';
import { MobileThemeProvider, useMobileTheme } from './src/lib/mobile-theme';
import { colors } from './src/styles/theme';

import LoginScreen from './src/screens/LoginScreen';
import RouteScreen from './src/screens/RouteScreen';
import CameraScreen from './src/screens/CameraScreen';
import ManualCodeScreen from './src/screens/ManualCodeScreen';
import HydrometerMatchScreen from './src/screens/HydrometerMatchScreen';
import OCRResultScreen from './src/screens/OCRResultScreen';
import DayHistoryScreen from './src/screens/DayHistoryScreen';

const Stack = createNativeStackNavigator();

function AppNavigator() {
  const { user, loading } = useAuth();
  const { mode } = useMobileTheme();

  if (loading) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: colors.navy950 }}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
  }

  return (
    <Stack.Navigator key={mode} screenOptions={{ headerShown: false, animation: 'slide_from_right' }}>
      {!user ? (
        <Stack.Screen name="Login" component={LoginScreen} />
      ) : (
        <>
          <Stack.Screen name="Route" component={RouteScreen} />
          <Stack.Screen name="Camera" component={CameraScreen} />
          <Stack.Screen name="ManualCode" component={ManualCodeScreen} />
          <Stack.Screen name="HydrometerMatch" component={HydrometerMatchScreen} />
          <Stack.Screen name="OCRResult" component={OCRResultScreen} />
          <Stack.Screen name="DayHistory" component={DayHistoryScreen} />
        </>
      )}
    </Stack.Navigator>
  );
}

function AppShell() {
  const { mode } = useMobileTheme();
  return (
    <FeedbackProvider>
      <NavigationContainer>
        <StatusBar hidden style={mode === 'dark' ? 'light' : 'dark'} translucent />
        <AppNavigator />
      </NavigationContainer>
    </FeedbackProvider>
  );
}

export default function App() {
  useEffect(() => {
    const applyImmersiveMode = () => {
      void NavigationBar.setBehaviorAsync('overlay-swipe');
      void NavigationBar.setVisibilityAsync('hidden');
      void NavigationBar.setButtonStyleAsync('light');
    };

    applyImmersiveMode();

    const subscription = AppState.addEventListener('change', (state: AppStateStatus) => {
      if (state === 'active') {
        applyImmersiveMode();
        setTimeout(applyImmersiveMode, 120);
        setTimeout(applyImmersiveMode, 600);
      }
    });

    const interval = setInterval(applyImmersiveMode, 2500);

    return () => {
      subscription.remove();
      clearInterval(interval);
    };
  }, []);

  return (
    <MobileThemeProvider>
      <AuthProvider>
        <AppShell />
      </AuthProvider>
    </MobileThemeProvider>
  );
}
