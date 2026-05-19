import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: {
    root: path.join(__dirname),
  },
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api",
    NEXT_PUBLIC_APP_BUILD:
      process.env.VERCEL_GIT_COMMIT_SHA ||
      process.env.RAILWAY_GIT_COMMIT_SHA ||
      "",
  },
  async rewrites() {
    return [
      { source: "/clientes", destination: "/customers" },
      { source: "/clientes/novo", destination: "/customers/new" },
      { source: "/clientes/:id", destination: "/customers/:id" },
      { source: "/clientes/:id/editar", destination: "/customers/:id/edit" },
      { source: "/hidrometros", destination: "/hydrometers" },
      { source: "/leituras", destination: "/readings" },
      { source: "/faturas", destination: "/invoices" },
      { source: "/faturas/:id", destination: "/invoices/:id" },
      { source: "/notificacoes", destination: "/notifications" },
      { source: "/conversas", destination: "/conversations" },
      { source: "/configuracoes", destination: "/settings" },
      { source: "/tarifas", destination: "/tariffs" },
      { source: "/painel", destination: "/dashboard" },
    ];
  },
};

export default nextConfig;
