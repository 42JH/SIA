import { useEffect, useRef } from 'react';
import { sendGazeCalibration } from '../../ws/gazeCalibration';
import styles from './DashboardGazeMeasurement.module.css';

export default function DashboardGazeMeasurement({ point, ready, connected, onFailure, onCancel }) {
  const target = useRef(null);
  const sentPoint = useRef(null);
  useEffect(() => {
    const check = () => { if (!document.fullscreenElement) onFailure('전체화면이 해제되었습니다. 측정을 중단한 뒤 다시 시도해주세요.'); };
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
      onFailure('화면 크기가 변경되었습니다. 측정을 중단한 뒤 다시 시도해주세요.');
    };
    document.addEventListener('fullscreenchange', check);
    window.addEventListener('resize', resized);
    return () => {
      clearTimeout(guardTimer);
      document.removeEventListener('fullscreenchange', check);
      window.removeEventListener('resize', resized);
    };
  }, [onFailure]);
  useEffect(() => {
    if (!point || !ready || !document.fullscreenElement || !target.current || sentPoint.current === point.n) return;
    if (!Number.isInteger(point.n) || point.n < 1 || point.n > 9) { onFailure('시선 측정 지점 번호가 올바르지 않습니다. 연결 상태를 확인해주세요.'); return; }
    const frame = requestAnimationFrame(() => {
      const rect = target.current.getBoundingClientRect();
      // TODO(BE): 다중 모니터의 물리 좌표 원점·배율 제공 계약이 없어 주 모니터 전체화면만 지원
      if (window.screenX !== 0 || window.screenY !== 0) { onFailure('주 모니터 전체화면에서 보정을 진행해주세요.'); return; }
      try {
        sendGazeCalibration('calib_point_shown', { n: point.n, x: Math.round((rect.x + rect.width / 2) * window.devicePixelRatio), y: Math.round((rect.y + rect.height / 2) * window.devicePixelRatio) });
        sentPoint.current = point.n;
      } catch (error) { onFailure(error.message); }
    });
    return () => cancelAnimationFrame(frame);
  }, [onFailure, point, ready]);
  return <div className={styles.measure}><p className={styles.guide}>튀어나온 두더지를 <strong>1초간 바라보면</strong> 잡힙니다</p><div className={styles.grid}>{Array.from({ length: 9 }, (_, index) => <div className={styles.cell} key={index}>{point?.n === index + 1 ? <div className={styles.mole}><span ref={target} className={styles.nose}>●</span><small>두더지</small></div> : <span className={styles.hole}>{point && index + 1 < point.n ? '잡음' : '대기'}</span>}</div>)}</div><div className={styles.controls}>{!ready && <p role="alert">연결 또는 화면 상태를 확인한 후 측정을 중단하고 다시 시도해주세요.</p>}<button onClick={onCancel} disabled={!connected}>측정 중단</button></div></div>;
}
