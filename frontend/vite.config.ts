import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ command }) => {
const apiTarget = process.env.CATALOG_LIVE_API_URL ?? "http://127.0.0.1:8000";
const injectedProductAnalyticsSource = process.env.VITE_PRODUCT_ANALYTICS_SOURCE;
if (command === "build" && injectedProductAnalyticsSource === undefined) {
  throw new Error("VITE_PRODUCT_ANALYTICS_SOURCE is required for a release build.");
}
const productAnalyticsSource = injectedProductAnalyticsSource ?? "legacy_parser";
if (productAnalyticsSource !== "legacy_parser" && productAnalyticsSource !== "p0_catalog") throw new Error("VITE_PRODUCT_ANALYTICS_SOURCE must be legacy_parser or p0_catalog.");
return {
  define: {
    __PRODUCT_ANALYTICS_SOURCE__: JSON.stringify(productAnalyticsSource),
  },
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: false,
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    strictPort: true,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: false,
      },
    },
  },
};
});
