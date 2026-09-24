import path from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": path.resolve(__dirname, "./src") },
  },
  build: {
    // The one chunk over the default 500 kB is three.js, which is already
    // split out and only loaded when the 4D tab opens.
    chunkSizeWarningLimit: 600,
  },
  server: {
    port: 5173,
    proxy: {
      // Keeps the browser on one origin in development.
      "/api": {
        target: process.env.VITE_API_TARGET ?? "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
