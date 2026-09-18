import { useEffect, useState } from "react";
import { useNotificationStore } from "../../store/notificationStore";
import styles from "./BootToast.module.css";

const VISIBLE_MS = 3000;

// 앱 켤 때 한 번, session_state{state:"PASSIVE"} (reason 없음) 수신 시 짧게 표시 (와이어프레임 16번)
export default function BootToast({ hidden = false }) {
  const bootToastShown = useNotificationStore((state) => state.bootToastShown);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (!bootToastShown) return;
    setVisible(true);
    const timer = setTimeout(() => setVisible(false), VISIBLE_MS);
    return () => clearTimeout(timer);
  }, [bootToastShown]);

  if (hidden || !visible) return null;

  return <div className={styles.toast} role="status"><span className={styles.logo} aria-hidden="true"><i /><i /><i /><i /><i /></span><p>SIA가 실행되었습니다.</p></div>;
}
