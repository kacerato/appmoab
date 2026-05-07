import { StyleSheet } from 'react-native';

export const colors = {
  navy950: '#F8FAFC',    // Background Principal
  navy900: '#FFFFFF',    // Headers/Cards
  navy800: '#FFFFFF',    // Cards
  navy700: '#F1F5F9',    // Secundário Hover
  navy600: '#E2E8F0',    // Bordas Hover
  accent: '#0077C8',     // Water Blue Vibrante
  accentHover: '#0062a3',
  cyan: '#00b4d8',
  success: '#10b981',
  warning: '#f59e0b',
  danger: '#ef4444',
  textPrimary: '#0F172A',
  textSecondary: '#334155',
  textMuted: '#64748B',
  border: '#E2E8F0',
};

export const shared = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.navy950,
  },
  safeArea: {
    flex: 1,
    backgroundColor: colors.navy950,
  },
  card: {
    backgroundColor: colors.navy800,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 20,
    marginBottom: 12,
  },
  input: {
    backgroundColor: colors.navy900,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    color: colors.textPrimary,
    fontSize: 15,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontFamily: 'System',
  },
  inputFocused: {
    borderColor: colors.accent,
  },
  label: {
    fontSize: 11,
    fontWeight: '700',
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 6,
  },
  btnPrimary: {
    backgroundColor: colors.accent,
    borderRadius: 10,
    paddingVertical: 14,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    flexDirection: 'row' as const,
    gap: 8,
  },
  btnPrimaryText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '700',
  },
  btnSecondary: {
    backgroundColor: colors.navy700,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: 'center' as const,
  },
  btnSecondaryText: {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: '600',
  },
  badge: {
    paddingHorizontal: 10,
    paddingVertical: 3,
    borderRadius: 99,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: '700',
  },
  title: {
    fontSize: 24,
    fontWeight: '800',
    color: colors.textPrimary,
    letterSpacing: -0.5,
  },
  subtitle: {
    fontSize: 13,
    color: colors.textMuted,
    marginTop: 2,
  },
  headerBar: {
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    justifyContent: 'space-between' as const,
    paddingHorizontal: 20,
    paddingVertical: 16,
    backgroundColor: colors.navy900,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
  },
});
