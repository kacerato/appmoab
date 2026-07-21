
export const lightColors = {
  navy950: '#F8FAFC',
  abyss: '#EFF6FF',
  navy900: '#FFFFFF',
  navy800: '#FFFFFF',
  navy700: '#E0F2FE',
  navy600: '#CBD5E1',
  sidebarNavy: '#FFFFFF',
  accent: '#0077C8',
  accentHover: '#005FA3',
  accentSoft: 'rgba(0, 119, 200, 0.08)',
  cyan: '#0077C8',
  coral: '#DC2626',
  success: '#059669',
  successSoft: 'rgba(5, 150, 105, 0.08)',
  warning: '#D97706',
  warningSoft: 'rgba(217, 119, 6, 0.08)',
  danger: '#DC2626',
  dangerSoft: 'rgba(220, 38, 38, 0.08)',
  textPrimary: '#0F172A',
  textSecondary: '#475569',
  textMuted: '#94A3B8',
  border: '#E2E8F0',
  borderHover: '#CBD5E1',
};

export const darkColors: typeof lightColors = {
  navy950: '#07111F',
  abyss: '#0B1728',
  navy900: '#0F1B2D',
  navy800: '#142238',
  navy700: '#1D3351',
  navy600: '#334B6B',
  sidebarNavy: '#0B1728',
  accent: '#38BDF8',
  accentHover: '#7DD3FC',
  accentSoft: 'rgba(56, 189, 248, 0.14)',
  cyan: '#22D3EE',
  coral: '#FB7185',
  success: '#34D399',
  successSoft: 'rgba(52, 211, 153, 0.14)',
  warning: '#FBBF24',
  warningSoft: 'rgba(251, 191, 36, 0.14)',
  danger: '#FB7185',
  dangerSoft: 'rgba(251, 113, 133, 0.14)',
  textPrimary: '#E5F0FF',
  textSecondary: '#B7C7DA',
  textMuted: '#7F95AE',
  border: '#213653',
  borderHover: '#335273',
};

export const colors = { ...lightColors };

export function applyColorMode(mode: 'light' | 'dark') {
  Object.assign(colors, mode === 'dark' ? darkColors : lightColors);
}

// These styles deliberately stay as plain objects instead of StyleSheet.create.
// `colors` is updated at runtime when the operator changes the theme; styles
// registered by StyleSheet.create capture the initial (light) color values.
export const shared: any = {
  get container() {
    return {
    flex: 1,
    backgroundColor: colors.navy950,
    };
  },
  get safeArea() {
    return {
    flex: 1,
    backgroundColor: colors.navy950,
    };
  },
  get pagePadding() {
    return {
    paddingHorizontal: 20,
    paddingVertical: 18,
    };
  },
  get card() {
    return {
    backgroundColor: colors.navy900,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 20,
    marginBottom: 14,
    shadowColor: '#0F172A',
    shadowOffset: { width: 0, height: 6 },
    shadowOpacity: 0.06,
    shadowRadius: 14,
    elevation: 2,
    };
  },
  get sectionTitle() {
    return {
    color: colors.textMuted,
    fontSize: 11,
    fontWeight: '800',
    marginBottom: 12,
    textTransform: 'uppercase',
    letterSpacing: 0.6,
    };
  },
  get input() {
    return {
    backgroundColor: colors.navy900,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    color: colors.textPrimary,
    fontSize: 15,
    paddingHorizontal: 14,
    paddingVertical: 12,
    };
  },
  get label() {
    return {
    fontSize: 11,
    fontWeight: '700',
    color: colors.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: 6,
    };
  },
  get btnPrimary() {
    return {
    backgroundColor: colors.accent,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    flexDirection: 'row' as const,
    gap: 8,
    };
  },
  get btnPrimaryText() {
    return {
    color: '#fff',
    fontSize: 15,
    fontWeight: '700',
    };
  },
  get btnSecondary() {
    return {
    backgroundColor: colors.navy700,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: 'center' as const,
    justifyContent: 'center' as const,
    };
  },
  get btnSecondaryText() {
    return {
    color: colors.textPrimary,
    fontSize: 14,
    fontWeight: '600',
    };
  },
  get title() {
    return {
    fontSize: 24,
    fontWeight: '800',
    color: colors.textPrimary,
    letterSpacing: 0,
    };
  },
  get subtitle() {
    return {
    fontSize: 13,
    color: colors.textMuted,
    marginTop: 2,
    };
  },
  get headerBar() {
    return {
    paddingHorizontal: 20,
    paddingVertical: 18,
    backgroundColor: colors.navy900,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    flexDirection: 'row' as const,
    alignItems: 'center' as const,
    justifyContent: 'space-between' as const,
    };
  },
  get glassCard() {
    return {
    backgroundColor: colors.navy900,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 18,
    };
  },
  get badge() {
    return {
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
    alignSelf: 'flex-start' as const,
    };
  },
  get badgeText() {
    return {
    fontSize: 11,
    fontWeight: '700',
    };
  },
};
