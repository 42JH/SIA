import { useEffect, useSyncExternalStore } from "react";
import { RouterProvider } from "react-router-dom";
import router from "./routes/router";
import { startFeSocket } from "./ws/feSocket";
import TopNotification from "./components/popup/TopNotification";
import BootToast from "./components/popup/BootToast";

export default function App() {
  const pathname = useSyncExternalStore(router.subscribe, () => router.state.location.pathname);
  const isOnboarding = pathname === '/' || pathname === '/onboarding' || pathname === '/dashboard/gaze/setup';
  // WS 연결은 앱 전체에서 한 번만 시작한다 (agents.md 1장 - 중복 연결 생성 금지)
  useEffect(() => {
    startFeSocket();
  }, []);

  return (
    <>
      {/* 첫 설정 중에는 명령 알림을 숨기고 기존 전역 팝업은 라우터 밖에서 유지 */}
      {!isOnboarding && <TopNotification />}
      <BootToast hidden={isOnboarding} />
      <RouterProvider router={router} />
    </>
  );
}
