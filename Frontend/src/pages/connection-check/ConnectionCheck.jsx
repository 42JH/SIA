import { useEffect, useState } from "react";
import { fetchStatus } from "../../api/status";
import { useSessionStore } from "../../store/sessionStore";
import { on } from "../../ws/eventBus";
import styles from "./ConnectionCheck.module.css";
import CommunicationLog from '../../components/onboarding/CommunicationLog';

const LOGGED_TYPES = [
  "listening",
  "session_state",
  "notice",
  "tool_result",
  "gesture_result",
  "voice_rejected",
  "error",
];

// REST(/api/status) + WS(/ws/fe) 실제 통신이 되는지 눈으로 확인하기 위한 페이지.
// mock 없이 실제 BE 호출만 한다 (agents.md 1장).
export default function ConnectionCheck() {
  const wsConnected = useSessionStore((state) => state.wsConnected);
  const [status, setStatus] = useState(null);
  const [statusError, setStatusError] = useState(null);
  const [wsLog, setWsLog] = useState([]);

  useEffect(() => {
    const unsubscribers = LOGGED_TYPES.map((type) =>
      on(type, (data) => {
        setWsLog((prev) => [{ type, data, at: new Date().toLocaleTimeString() }, ...prev].slice(0, 20));
      })
    );
    return () => unsubscribers.forEach((unsubscribe) => unsubscribe());
  }, []);

  async function handleCheckStatus() {
    setStatusError(null);
    try {
      const data = await fetchStatus();
      setStatus(data);
    } catch (error) {
      setStatusError(error.message);
    }
  }

  return (
    <div className={styles.page}>
      <h1>통신 확인</h1>
      <CommunicationLog />

      <section>
        <h2>WS (ws://127.0.0.1:8080/ws/fe)</h2>
        <p>연결 상태: {wsConnected ? "연결됨" : "연결 안 됨"}</p>
        <ul>
          {wsLog.map((entry, index) => (
            <li key={index}>
              [{entry.at}] {entry.type} — {JSON.stringify(entry.data)}
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>REST (GET /api/status)</h2>
        <button onClick={handleCheckStatus}>상태 조회</button>
        {statusError && <p className={styles.error}>에러: {statusError}</p>}
        {status && <pre>{JSON.stringify(status, null, 2)}</pre>}
      </section>
    </div>
  );
}
