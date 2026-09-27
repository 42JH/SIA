import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 개발 단계는 Tauri와 무관한 순수 웹 React 앱으로 실행한다 (agents.md 0장)
export default defineConfig({
  plugins: [react()],
});
