
export const lightColors = {
  navy950: '#F6FAFC',
  abyss: '#F1F7FA',
  navy900: '#FFFFFF',
  navy800: '#FFFFFF',
  navy700: '#EAF6FA',
  navy600: '#D7E5EC',
  sidebarNavy: '#FFFFFF',
  accent: '#00A6D4',
  accentHover: '#008CB7',
  accentSoft: 'rgba(0, 166, 212, 0.10)',
  cyan: '#00B7D9',
  coral: '#EF5B67',
  success: '#1BAF72',
  successSoft: 'rgba(27, 175, 114, 0.10)',
  warning: '#E99A2E',
  warningSoft: 'rgba(233, 154, 46, 0.11)',
  danger: '#EF4E5D',
  dangerSoft: 'rgba(239, 78, 93, 0.10)',
  textPrimary: '#081B3A',
  textSecondary: '#536580',
  textMuted: '#8493A7',
  border: '#E1EAF0',
  borderHover: '#C9D8E1',
};

export const darkColors: typeof lightColors = {
  navy950: '#071521',
  abyss: '#0B1B29',
  navy900: '#0E2030',
  navy800: '#112638',
  navy700: '#18354A',
  navy600: '#294A60',
  sidebarNavy: '#0B1B29',
  accent: '#31C4E8',
  accentHover: '#70D8F1',
  accentSoft: 'rgba(49, 196, 232, 0.14)',
  cyan: '#37D0EA',
  coral: '#FB7185',
  success: '#42D49A',
  successSoft: 'rgba(66, 212, 154, 0.14)',
  warning: '#F7B955',
  warningSoft: 'rgba(247, 185, 85, 0.14)',
  danger: '#FB7185',
  dangerSoft: 'rgba(251, 113, 133, 0.14)',
  textPrimary: '#EDF7FC',
  textSecondary: '#B8CAD8',
  textMuted: '#8198AA',
  border: '#203A4D',
  borderHover: '#31566D',
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
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 18,
    marginBottom: 12,
    shadowColor: '#0B3150',
    shadowOffset: { width: 0, height: 5 },
    shadowOpacity: 0.045,
    shadowRadius: 12,
    elevation: 1,
    };
  },
  get sectionTitle() {
    return {
    color: colors.textSecondary,
    fontSize: 12,
    fontWeight: '800',
    marginBottom: 12,
    letterSpacing: 0.2,
    };
  },
  get input() {
    return {
    backgroundColor: colors.navy900,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 14,
    color: colors.textPrimary,
    fontSize: 15,
    paddingHorizontal: 14,
    paddingVertical: 14,
    };
  },
  get label() {
    return {
    fontSize: 11,
    fontWeight: '700',
    color: colors.textMuted,
    letterSpacing: 0.2,
    marginBottom: 6,
    };
  },
  get btnPrimary() {
    return {
    backgroundColor: colors.accent,
    borderRadius: 14,
    paddingVertical: 15,
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
    backgroundColor: colors.navy900,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 14,
    paddingVertical: 14,
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
    backgroundColor: colors.navy950,
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
    borderRadius: 18,
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
