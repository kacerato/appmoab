import React, { useEffect } from 'react';
import { ActivityIndicator, View } from 'react-native';
import { StatusBar } from 'expo-status-bar';
import * as NavigationBar from 'expo-navigation-bar';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { AuthProvider, useAuth } from './src/lib/auth';
import { FeedbackProvider } from './src/lib/feedback';
import { colors } from './src/styles/theme';

import LoginScreen from './src/screens/LoginScreen';
import RouteScreen from './src/screens/RouteScreen';
import CameraScreen from './src/screens/CameraScreen';
import HydrometerMatchScreen from './src/screens/HydrometerMatchScreen';
import OCRResultScreen from './src/screens/OCRResultScreen';
import DayHistoryScreen from './src/screens/DayHistoryScreen';

const Stack = createNativeStackNavigator();

function AppNavigator() {
  const { user, loading } = useAuth();

  if (loading) {
    return (
      <View style={{ flex: 1, justifyContent: 'center', alignItems: 'center', backgroundColor: colors.navy950 }}>
        <ActivityIndicator size="large" color={colors.accent} />
      </View>
    );
  }

  return (
    <Stack.Navigator screenOptions={{ headerShown: false, animation: 'slide_from_right' }}>
      {!user ? (
        <Stack.Screen name="Login" component={LoginScreen} />
      ) : (
        <>
          <Stack.Screen name="Route" component={RouteScreen} />
          <Stack.Screen name="Camera" component={CameraScreen} />
          <Stack.Screen name="HydrometerMatch" component={HydrometerMatchScreen} />
          <Stack.Screen name="OCRResult" component={OCRResultScreen} />
          <Stack.Screen name="DayHistory" component={DayHistoryScreen} />
        </>
      )}
    </Stack.Navigator>
  );
}

export default function App() {
  useEffect(() => {
    void NavigationBar.setBehaviorAsync('overlay-swipe');
    void NavigationBar.setVisibilityAsync('hidden');
    void NavigationBar.setBackgroundColorAsync(colors.navy950);
    void NavigationBar.setButtonStyleAsync('light');
  }, []);

  return (
    <AuthProvider>
      <FeedbackProvider>
        <NavigationContainer>
          <StatusBar hidden style="light" translucent />
          <AppNavigator />
        </NavigationContainer>
      </FeedbackProvider>
    </AuthProvider>
  );
}
