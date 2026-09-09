import { useEffect, useState } from "react";
import { fetchSettings } from "../../api/settings";

// 대시보드(설정 · 제스처 · 시선 · 음성) 섹션은 여기 아래에 섹션별 파일로 추가한다.
// 예: SettingsSection.jsx, GestureSection.jsx, VoiceSection.jsx, CalibSection.jsx ...
// 지금은 GET /api/settings 통신만 실제로 확인한다.
export default function DashboardHome() {
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchSettings()
      .then(setSettings)
      .catch((err) => setError(err.message));
  }, []);

  return (
    <div>
      <h1>대시보드 (설정 통신 확인)</h1>
      {error && <p>에러: {error}</p>}
      {settings && <pre>{JSON.stringify(settings, null, 2)}</pre>}
    </div>
  );
}
