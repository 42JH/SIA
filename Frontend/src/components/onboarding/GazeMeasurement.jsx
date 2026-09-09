import { useEffect, useRef } from 'react';
import { sendOnboarding } from '../../ws/onboarding';
import { useOnboardingStore } from '../../store/onboardingStore';
import styles from './GazeMeasurement.module.css';

export default function GazeMeasurement({ point, ready, onCancel }) {
  const target = useRef(null);
  const fail = (error) => useOnboardingStore.getState().change({ error, interrupted: true });
  useEffect(() => {
    const check = () => { if (!document.fullscreenElement) fail('전체화면이 해제되었습니다. 보정을 다시 시작해주세요.'); };
    const resized = () => fail('화면 크기가 변경되었습니다. 보정을 다시 시작해주세요.');
    document.addEventListener('fullscreenchange', check);
    window.addEventListener('resize', resized);
    return () => { document.removeEventListener('fullscreenchange', check); window.removeEventListener('resize', resized); };
  }, []);
  useEffect(() => {
    if (!point || !ready || !document.fullscreenElement || !target.current) return;
    const frame = requestAnimationFrame(() => {
      const rect = target.current.getBoundingClientRect();
      // TODO(BE): 다중 모니터의 물리 좌표 원점·배율 제공 계약이 없어 주 모니터 전체화면만 지원
      if (window.screenX !== 0 || window.screenY !== 0) { fail('주 모니터 전체화면에서 보정을 진행해주세요.'); return; }
      try { sendOnboarding('calib_point_shown', { n: point.n, x: Math.round((rect.x + rect.width / 2) * window.devicePixelRatio), y: Math.round((rect.y + rect.height / 2) * window.devicePixelRatio) }); }
      catch (error) { fail(error.message); }
    });
    return () => cancelAnimationFrame(frame);
  }, [point, ready]);
  return <div className={styles.measure}><p className={styles.guide}>튀어나온 두더지를 <strong>1초간 바라보면</strong> 잡힙니다</p><div className={styles.grid}>{Array.from({ length: 9 }, (_, index) => <div className={styles.cell} key={index}>{point?.n === index + 1 ? <div className={styles.mole}><span ref={target} className={styles.nose}>●</span><small>두더지</small></div> : <span className={styles.hole}>{point && index + 1 < point.n ? '잡음' : '대기'}</span>}</div>)}</div><div className={styles.controls}>{!ready && <p role="alert">연결 또는 화면 상태를 확인한 후 처음부터 다시 설정해주세요.</p>}<button onClick={onCancel} disabled={!ready}>측정 중단</button>{!ready && <button onClick={() => useOnboardingStore.getState().change({ step: 'welcome', interrupted: false, pending: false })}>처음부터 다시 설정</button>}</div></div>;
}
