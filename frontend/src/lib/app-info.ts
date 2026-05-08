import packageJson from "../../package.json";

export const FRONTEND_VERSION = packageJson.version;
export const FRONTEND_FRAMEWORK = "Next.js 16";
export const BACKEND_FRAMEWORK = "FastAPI (Python)";
export const DEPLOY_TARGET = "Vercel + Railway";
export const BUILD_REVISION =
  process.env.NEXT_PUBLIC_APP_BUILD ||
  process.env.NEXT_PUBLIC_VERCEL_GIT_COMMIT_SHA ||
  process.env.NEXT_PUBLIC_RAILWAY_GIT_COMMIT_SHA ||
  "";
