import { defineConfig } from "vite";

// 開發時將 /api 代理到 FastAPI 後端，避免 CORS 與硬編碼網址。
// 部署時前端為靜態檔，後端網址由 VITE_API_BASE 環境變數覆寫（見 src/api.ts）。
export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
