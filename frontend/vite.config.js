import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// All API calls are same-origin ("/incidents", "/ingest/...", ...) and proxied to
// the FastAPI backend — no CORS configuration needed on the backend.
const API = process.env.VITE_API_TARGET || "http://localhost:8000";

const proxy = Object.fromEntries(
  ["/incidents", "/health", "/suppressions", "/quantum", "/providers", "/assessments", "/ingest", "/demo"].map((p) => [
    p,
    { target: API, changeOrigin: true },
  ])
);

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  preview: { port: 5173, proxy },
});
