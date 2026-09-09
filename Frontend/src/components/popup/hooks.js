import { useEffect, useState } from "react";

// 초 단위 카운트다운 (파괴적 명령 확인 팝업 등, 서버가 준 timeoutSec 기준)
export function useCountdownFromSeconds(totalSec) {
  const [remaining, setRemaining] = useState(totalSec);

  useEffect(() => {
    setRemaining(totalSec);
    const interval = setInterval(() => {
      setRemaining((prev) => Math.max(prev - 1, 0));
    }, 1000);
    return () => clearInterval(interval);
  }, [totalSec]);

  return remaining;
}

// epoch millis 기준 카운트다운 (session_state의 deadlineMs 기준, FR-022)
export function useCountdownToDeadline(deadlineMs) {
  const [remainingSec, setRemainingSec] = useState(
    Math.max(Math.round((deadlineMs - Date.now()) / 1000), 0)
  );

  useEffect(() => {
    const interval = setInterval(() => {
      setRemainingSec(Math.max(Math.round((deadlineMs - Date.now()) / 1000), 0));
    }, 500);
    return () => clearInterval(interval);
  }, [deadlineMs]);

  return remainingSec;
}
