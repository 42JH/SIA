import { createBrowserRouter } from "react-router-dom";
import ConnectionCheck from "../pages/connection-check/ConnectionCheck";
import OnboardingHome from "../pages/onboarding/OnboardingHome";
import DashboardHome from "../pages/dashboard/DashboardHome";
import GazeCalibrationPage from "../pages/dashboard/GazeCalibrationPage";

// 라우터에 직접 연결되는 화면은 pages 아래에서만 가져온다 (agents.md 1장, 3장)
const router = createBrowserRouter([
  { path: "/", element: <OnboardingHome /> },
  { path: "/connection-check", element: <ConnectionCheck /> },
  { path: "/onboarding", element: <OnboardingHome /> },
  { path: "/dashboard", element: <DashboardHome /> },
  { path: "/dashboard/gaze/setup", element: <GazeCalibrationPage /> },
]);

export default router;
