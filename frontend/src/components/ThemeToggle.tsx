'use client';

import { Sun, Moon } from 'lucide-react';
import { useTheme } from './ThemeProvider';

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();

  return (
    <div className="theme-toggle-wrapper">
      <button
        className={`theme-option ${theme === 'light' ? 'active' : ''}`}
        onClick={() => setTheme('light')}
        aria-pressed={theme === 'light'}
        aria-label="Tema Claro"
      >
        <Sun size={14} />
        <span>Claro</span>
      </button>
      <button
        className={`theme-option ${theme === 'dark' ? 'active' : ''}`}
        onClick={() => setTheme('dark')}
        aria-pressed={theme === 'dark'}
        aria-label="Tema Escuro"
      >
        <Moon size={14} />
        <span>Escuro</span>
      </button>
    </div>
  );
}
