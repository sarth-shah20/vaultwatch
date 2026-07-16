import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// All API calls are same-origin ("/incidents", "/health", ...) and proxied to the
// FastAPI backend on :8000 — no CORS changes needed on the backend.
const proxy = Object.fromEntries(
  ["/incidents", "/health", "/suppressions"].map((p) => [
    p,
    { target: "http://localhost:8000", changeOrigin: true },
  ])
);

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  preview: { port: 5173, proxy },
});
