import { useEffect, useState } from "react";
import { useNotificationStore } from "../../store/notificationStore";
import { sendUserChoice } from "../../ws/notifications";
import { useCountdownFromSeconds, useCountdownToDeadline } from "./hooks";
import styles from "./TopNotification.module.css";

export default function TopNotification() {
  const notification = useNotificationStore((state) => state.topNotification);
  if (!notification) return null;

  return (
    <aside className={`${styles.container} ${styles[notification.kind] ?? ""}`} aria-live="polite">
      {renderContent(notification)}
    </aside>
  );
}

function renderContent(notification) {
  switch (notification.kind) {
    case "listening":
      return <NotificationRow icon="microphone" message="듣는 중..." />;
    case "progress":
      return <NotificationRow icon="spinner" message={notification.message || "실행 중..."} />;
    case "success":
      return <NotificationRow icon="check" message={notification.message} />;
    case "notice":
      return <NotificationRow icon="info" message={notification.message} />;
    case "confirm":
      return <ConfirmContent notification={notification} />;
    case "unknown_command":
      return <UnknownCommandContent notification={notification} />;
    case "summary":
      return <SummaryContent notification={notification} />;
    case "choices":
      return <ChoicesContent notification={notification} />;
    case "capture_saved":
      return <CaptureContent notification={notification} />;
    case "voice_rejected":
      return <NotificationRow icon="warning" message={notification.message} />;
    case "error":
      return <NotificationRow icon="warning" message={notification.message} />;
    case "session_countdown":
      return <SessionCountdownContent deadlineMs={notification.deadlineMs} />;
    default:
      return null;
  }
}

function NotificationRow({ icon, message, trailing = null }) {
  return (
    <div className={styles.row}>
      <NotificationIcon name={icon} />
      <p className={styles.message}>{message}</p>
      {trailing}
    </div>
  );
}

function ConfirmContent({ notification }) {
  const remaining = useCountdownFromSeconds(notification.timeoutSec);
  const dismiss = useNotificationStore((state) => state.dismissNotification);

  useEffect(() => {
    if (remaining === 0) dismiss();
  }, [dismiss, remaining]);

  return (
    <NotificationRow
      icon="question"
      message={notification.message}
      trailing={<Countdown value={remaining} />}
    />
  );
}

function UnknownCommandContent({ notification }) {
  return (
    <div className={styles.detailContent}>
      <NotificationRow icon="question" message={notification.message} />
      {notification.transcript && (
        <div className={styles.transcriptBlock}>
          <span className={styles.caption}>인식된 말</span>
          <p className={styles.transcript}>“{notification.transcript}”</p>
        </div>
      )}
    </div>
  );
}

function SummaryContent({ notification }) {
  return (
    <div className={styles.detailContent}>
      <NotificationRow
        icon="summary"
        message={notification.message}
        trailing={notification.items.length > 0
          ? <span className={styles.count}>{notification.items.length}문장</span>
          : null}
      />
      {notification.items.length > 0 && (
        <ol className={styles.summaryList}>
          {notification.items.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}
        </ol>
      )}
    </div>
  );
}

function ChoicesContent({ notification }) {
  const dismiss = useNotificationStore((state) => state.dismissNotification);
  const remaining = useCountdownFromSeconds(notification.timeoutSec);
  const [error, setError] = useState("");

  useEffect(() => {
    if (remaining === 0) dismiss();
  }, [dismiss, remaining]);

  function choose(n) {
    try {
      sendUserChoice(notification.choiceId, n);
      dismiss();
    } catch (sendError) {
      setError(sendError.message);
    }
  }

  return (
    <div className={styles.detailContent}>
      <NotificationRow
        icon="question"
        message={notification.message}
        trailing={<Countdown value={remaining} />}
      />
      <div className={styles.choiceList}>
        {notification.choices.map((choice) => (
          <button type="button" className={styles.choiceButton} key={choice.n} onClick={() => choose(choice.n)}>
            <span>{choice.label}</span>
            {choice.detail && <small>{choice.detail}</small>}
          </button>
        ))}
        <button type="button" className={styles.cancelButton} onClick={() => choose(null)}>취소</button>
      </div>
      {error && <p className={styles.inlineError} role="alert">{error}</p>}
    </div>
  );
}

function CaptureContent({ notification }) {
  const src = notification.url?.startsWith("/api/captures/")
    ? `http://127.0.0.1:8080${notification.url}`
    : null;
  return (
    <div className={styles.captureContent}>
      <NotificationIcon name="check" />
      {src && <img className={styles.captureImage} src={src} alt="저장된 화면 캡처" />}
      <div className={styles.captureMeta}>
        <p className={styles.message}>{notification.path}</p>
        {notification.width && notification.height && (
          <span className={styles.caption}>{notification.width} × {notification.height}</span>
        )}
      </div>
    </div>
  );
}

function SessionCountdownContent({ deadlineMs }) {
  const remaining = useCountdownToDeadline(deadlineMs);
  const dismiss = useNotificationStore((state) => state.dismissNotification);

  useEffect(() => {
    if (remaining === 0) dismiss();
  }, [dismiss, remaining]);

  return <NotificationRow icon="clock" message={`${remaining}초 후 대기 상태로 돌아갑니다.`} />;
}

function Countdown({ value }) {
  return <span className={styles.countdown} aria-label={`${value}초 남음`}>{value}</span>;
}

function NotificationIcon({ name }) {
  return (
    <span className={`${styles.icon} ${name === "spinner" ? styles.spinner : ""}`} aria-hidden="true">
      {name !== "spinner" && <IconSvg name={name} />}
    </span>
  );
}

function IconSvg({ name }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round", strokeLinejoin: "round" };
  if (name === "microphone") return <svg viewBox="0 0 24 24" {...common}><rect x="8" y="3" width="8" height="13" rx="4" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3M9 21h6" /></svg>;
  if (name === "check") return <svg viewBox="0 0 24 24" {...common}><path d="m6 12 4 4 8-9" /></svg>;
  if (name === "warning") return <svg viewBox="0 0 24 24" {...common}><path d="M12 5v9M12 18h.01" /></svg>;
  if (name === "info") return <svg viewBox="0 0 24 24" {...common}><path d="M12 10v7M12 7h.01" /></svg>;
  if (name === "summary") return <svg viewBox="0 0 24 24" {...common}><path d="M7 8h10M7 12h10M7 16h6" /></svg>;
  if (name === "clock") return <svg viewBox="0 0 24 24" {...common}><circle cx="12" cy="12" r="8" /><path d="M12 8v5l3 2" /></svg>;
  return <svg viewBox="0 0 24 24" {...common}><path d="M9.7 9a2.5 2.5 0 1 1 3.5 2.3c-.8.4-1.2.9-1.2 1.7M12 17h.01" /></svg>;
}
