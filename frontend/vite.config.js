import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The dashboard always calls /api (see src/api/client.js). In Docker nginx
// forwards that prefix to the backend container; here Vite does the same job so
// a local `npm run dev` needs no separate configuration.
const apiProxy = {
  "/api": {
    target: process.env.VITE_DEV_API_TARGET ?? "http://127.0.0.1:8000",
    changeOrigin: true,
    // FastAPI mounts its routes at the root, so the prefix is stripped.
    rewrite: (path) => path.replace(/^\/api/, ""),
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    strictPort: true,
    open: false,
    proxy: apiProxy,
  },
  preview: {
    port: 3000,
    strictPort: true,
    proxy: apiProxy,
  },
});
