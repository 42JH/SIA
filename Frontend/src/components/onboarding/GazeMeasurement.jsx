import { useEffect, useRef } from 'react';
import { sendOnboarding } from '../../ws/onboarding';
import { useOnboardingStore } from '../../store/onboardingStore';
import styles from './GazeMeasurement.module.css';

export default function GazeMeasurement({ point, ready, connected, onCancel }) {
  const target = useRef(null);
  const sentPoint = useRef(null);
  const fail = (error) => useOnboardingStore.getState().interrupt(error);
  useEffect(() => {
    const check = () => { if (!document.fullscreenElement) fail('전체화면이 해제되었습니다. 보정을 다시 시작해주세요.'); };
    let resizeGuardReady = false;
    let measuredWidth = window.innerWidth;
    let measuredHeight = window.innerHeight;
    const guardTimer = setTimeout(() => {
      measuredWidth = window.innerWidth;
      measuredHeight = window.innerHeight;
      resizeGuardReady = true;
    }, 1000);
    const resized = () => {
      if (!resizeGuardReady || (window.innerWidth === measuredWidth && window.innerHeight === measuredHeight)) return;
      fail('화면 크기가 변경되었습니다. 보정을 다시 시작해주세요.');
    };
    document.addEventListener('fullscreenchange', check);
    window.addEventListener('resize', resized);
    return () => {
      clearTimeout(guardTimer);
      document.removeEventListener('fullscreenchange', check);
      window.removeEventListener('resize', resized);
    };
  }, []);
  useEffect(() => {
    if (!point || !ready || !document.fullscreenElement || !target.current || sentPoint.current === point.n) return;
    if (!Number.isInteger(point.n) || point.n < 1 || point.n > 9) { fail('시선 측정 지점 번호가 올바르지 않습니다. 연결 상태를 확인해주세요.'); return; }
    const frame = requestAnimationFrame(() => {
      const rect = target.current.getBoundingClientRect();
      try {
        sendOnboarding('calib_point_shown', { n: point.n, x: Math.round((rect.x + rect.width / 2) * window.devicePixelRatio), y: Math.round((rect.y + rect.height / 2) * window.devicePixelRatio) });
        sentPoint.current = point.n;
      }
      catch (error) { fail(error.message); }
    });
    return () => cancelAnimationFrame(frame);
  }, [point, ready]);
  return <div className={styles.measure}><p className={styles.guide}>튀어나온 두더지를 <strong>1초간 바라보면</strong> 잡힙니다</p><div className={styles.grid}>{Array.from({ length: 9 }, (_, index) => <div className={styles.cell} key={index}>{point?.n === index + 1 ? <div className={styles.mole}><span ref={target} className={styles.nose}>●</span><small>두더지</small></div> : <span className={styles.hole}>{point && index + 1 < point.n ? '잡음' : '대기'}</span>}</div>)}</div><div className={styles.controls}>{!ready && <p role="alert">연결 또는 화면 상태를 확인한 후 처음부터 다시 설정해주세요.</p>}<button onClick={onCancel} disabled={!connected}>측정 중단</button>{!ready && <button onClick={() => useOnboardingStore.getState().change({ step: 'welcome', interrupted: false, pending: false })}>처음부터 다시 설정</button>}</div></div>;
}
