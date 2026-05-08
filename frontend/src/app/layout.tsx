import type { Metadata } from 'next';
import './globals.css';
import { AppFeedbackProvider } from '@/components/AppFeedbackProvider';

export const metadata: Metadata = {
  title: 'AquaMoab — Gestão de Distribuição de Água',
  description: 'Sistema de gestão de clientes, leitura de hidrômetros e faturamento para distribuição de água de poço artesiano.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>
        <AppFeedbackProvider>{children}</AppFeedbackProvider>
      </body>
    </html>
  );
}
