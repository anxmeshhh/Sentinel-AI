import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    watch: { usePolling: true }, // reliable file-change detection in Docker on Windows hosts
  },
});
