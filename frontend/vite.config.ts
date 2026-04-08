import path from "path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
    dedupe: ["react", "react-dom"],
  },
  optimizeDeps: {
    include: [
      "react",
      "react-dom",
      "react/jsx-runtime",
      "react/jsx-dev-runtime",
      "@mantine/core",
      "@mantine/hooks",
      "@mantine/dates",
      "@mantine/charts",
      "@mantine/notifications",
      "recharts",
      "dayjs",
    ],
  },
  server: {
    port: 5173,
  },
});
