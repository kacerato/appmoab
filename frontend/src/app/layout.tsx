import type { Metadata } from 'next';
import './globals.css';
import { AppFeedbackProvider } from '@/components/AppFeedbackProvider';
import { ThemeProvider } from '@/components/ThemeProvider';

export const metadata: Metadata = {
  title: 'AquaMoab - Gestao de Distribuicao de Agua',
  description: 'Sistema de gestao de clientes, leitura de hidrometros e faturamento para distribuicao de agua de poco artesiano.',
  icons: {
    icon: '/icon.svg',
    shortcut: '/icon.svg',
    apple: '/icon.svg',
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <body>
        <ThemeProvider>
          <AppFeedbackProvider>{children}</AppFeedbackProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
