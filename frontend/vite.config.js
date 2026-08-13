import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Port 3000 is fixed: the FastAPI backend only allows CORS from localhost:3000.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    strictPort: true,
    open: false,
  },
  preview: {
    port: 3000,
    strictPort: true,
  },
});
