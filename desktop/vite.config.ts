import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.VITE_API_TARGET || "http://127.0.0.1:8765";
  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: Number(env.VITE_PORT) || 5173,
      strictPort: true,
      allowedHosts: true,
      proxy: {
        "/api": { target, changeOrigin: true, ws: false },
      },
    },
    preview: { host: "0.0.0.0", port: 4173, allowedHosts: true },
    build: { outDir: "dist", sourcemap: false, target: "es2022" },
    test: { environment: "jsdom", include: ["src/**/*.test.ts", "src/**/*.test.tsx"] },
  };
});
