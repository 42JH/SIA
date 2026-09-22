import { useEffect } from "react";
import { RouterProvider } from "react-router-dom";
import router from "./routes/router";
import { startFeSocket } from "./ws/feSocket";

export default function App() {
  // WS 연결은 앱 전체에서 한 번만 시작한다 (agents.md 1장 - 중복 연결 생성 금지)
  useEffect(() => {
    startFeSocket();
  }, []);

  return <RouterProvider router={router} />;
}
