import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const backend = { target: "http://127.0.0.1:8000", changeOrigin: false };

export default defineConfig({
  plugins: [react()],
  server: {
    // API сравнивает Origin с исходным Host браузера.
    proxy: {
      "^/api(?:/|$)": backend,
      "^/healthz(?:[?]|$)": backend,
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
  },
});
