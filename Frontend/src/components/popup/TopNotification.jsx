import { useNotificationStore } from "../../store/notificationStore";
import { useCountdownFromSeconds, useCountdownToDeadline } from "./hooks";
import styles from "./TopNotification.module.css";

// /ws/fe 이벤트 8종을 하나의 상태머신으로 표시 (와이어프레임 15번, 대화로 확정한 매핑표 기준)
export default function TopNotification() {
  const topNotification = useNotificationStore((state) => state.topNotification);

  if (!topNotification) return null;

  return <div className={styles.container}>{renderContent(topNotification)}</div>;
}

function renderContent(notification) {
  switch (notification.kind) {
    case "listening":
      return <span>듣는 중...</span>;

    case "executing":
      return <span>실행 중...</span>;

    case "notice":
      return <span>{notification.message}</span>;

    case "confirm":
      return <ConfirmContent message={notification.message} timeoutSec={notification.timeoutSec} />;

    case "file_deleted":
      return (
        <span>
          {notification.message}
          {/* TODO(BE): 파일 복원 방식(REST 추가 / Tauri invoke / 미구현) 미확정 - 우선 비활성 */}
          <button className={styles.undoButton} disabled title="복원 방식 미확정">
            되돌리기
          </button>
        </span>
      );

    case "unknown_command":
      return (
        <div>
          <div>{notification.message}</div>
          {notification.transcript && (
            <div className={styles.transcript}>인식된 말: "{notification.transcript}"</div>
          )}
        </div>
      );

    case "voice_rejected":
      return <span>{notification.message}</span>;

    case "session_countdown":
      return <SessionCountdownContent deadlineMs={notification.deadlineMs} />;

    default:
      return null;
  }
}

function ConfirmContent({ message, timeoutSec }) {
  const remaining = useCountdownFromSeconds(timeoutSec);
  return (
    <span>
      {message} ({remaining})
    </span>
  );
}

function SessionCountdownContent({ deadlineMs }) {
  const remainingSec = useCountdownToDeadline(deadlineMs);
  return <span>{remainingSec}초 후 대기 상태로 돌아갑니다.</span>;
}
