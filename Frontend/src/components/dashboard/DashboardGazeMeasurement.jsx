import { useEffect, useRef, useState } from 'react';
import { sendGazeCalibration } from '../../ws/gazeCalibration';
import moleImage from '../../assets/gaze-mole.png';
import moleHitImage from '../../assets/gaze-mole-hit.png';
import styles from './DashboardGazeMeasurement.module.css';

const cells = Array.from({ length: 9 }, (_, index) => index + 1);

export default function DashboardGazeMeasurement({ point, ready, connected, onFailure, onCancel }) {
  const target = useRef(null);
  const sentPoints = useRef(new Set());
  const displayedPoint = useRef(null);
  const transitionTimer = useRef(null);
  const [introDone, setIntroDone] = useState(false);
  const [activePoint, setActivePoint] = useState(null);
  const [hitPoint, setHitPoint] = useState(null);
  const [caught, setCaught] = useState(() => new Set());

  useEffect(() => {
    const timer = setTimeout(() => setIntroDone(true), 700); // 추정값 - 원본 이미지에서 명확히 확인 불가
    return () => clearTimeout(timer);
  }, []);

  useEffect(() => {
    const check = () => { if (!document.fullscreenElement) onFailure('전체화면이 해제되었습니다. 측정을 중단한 뒤 다시 시도해주세요.'); };
    const escape = (event) => { if (event.key === 'Escape' && document.fullscreenElement) onCancel(); };
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
    document.addEventListener('keydown', escape);
    window.addEventListener('resize', resized);
    return () => {
      clearTimeout(guardTimer);
      document.removeEventListener('fullscreenchange', check);
      document.removeEventListener('keydown', escape);
      window.removeEventListener('resize', resized);
    };
  }, [onCancel, onFailure]);

  useEffect(() => {
    if (!introDone || !point) return undefined;
    if (!Number.isInteger(point.n) || point.n < 1 || point.n > 9) {
      onFailure('시선 측정 지점 번호가 올바르지 않습니다. 연결 상태를 확인해주세요.');
      return undefined;
    }
    const previous = displayedPoint.current;
    if (previous == null) {
      displayedPoint.current = point.n;
      setActivePoint(point.n);
      return undefined;
    }
    if (previous === point.n) return undefined;

    // TODO(BE): calib_point_done을 FE까지 중계하면 다음 지점 도착 추론 대신 해당 이벤트로 명중 처리 필요
    setActivePoint(null);
    setHitPoint(previous);
    clearTimeout(transitionTimer.current);
    transitionTimer.current = setTimeout(() => {
      setCaught((items) => new Set(items).add(previous));
      displayedPoint.current = point.n;
      setHitPoint(null);
      setActivePoint(point.n);
    }, 420); // 추정값 - 원본 이미지에서 명확히 확인 불가
    return () => clearTimeout(transitionTimer.current);
  }, [introDone, onFailure, point]);

  useEffect(() => {
    if (!activePoint || !ready || !document.fullscreenElement || !target.current || sentPoints.current.has(activePoint)) return undefined;
    let secondFrame;
    const firstFrame = requestAnimationFrame(() => {
      secondFrame = requestAnimationFrame(() => {
        const rect = target.current?.getBoundingClientRect();
        if (!rect) return;
        try {
          sendGazeCalibration('calib_point_shown', {
            n: activePoint,
            x: Math.round((rect.left + rect.width / 2) * window.devicePixelRatio),
            y: Math.round((rect.top + rect.height / 2) * window.devicePixelRatio),
          });
          sentPoints.current.add(activePoint);
        } catch (error) { onFailure(error.message); }
      });
    });
    return () => { cancelAnimationFrame(firstFrame); cancelAnimationFrame(secondFrame); };
  }, [activePoint, onFailure, ready]);

  return <div className={styles.measure}>
    <p className={styles.guide}>튀어나온 두더지의 코를 <strong>1초간 바라보면</strong> 잡힙니다.</p>
    <button className={styles.stopButton} onClick={onCancel} disabled={!connected}>측정 중단</button>
    <div className={styles.grid}>{cells.map((number) => {
      const state = hitPoint === number ? 'hit' : activePoint === number ? 'active' : caught.has(number) ? 'caught' : 'ready';
      return <div className={`${styles.cell} ${styles[state]}`} key={number}>
        <span className={styles.hole} aria-hidden="true" />
        {state === 'caught' && <><span className={styles.caughtMark}>✓</span><small>잡음</small></>}
        {state === 'ready' && <small>대기</small>}
        {state === 'active' && <div className={styles.targetGroup}><span className={styles.lock}><b>1초</b></span><img src={moleImage} alt="두더지" /><span ref={target} className={styles.noseAnchor} aria-hidden="true" /></div>}
        {state === 'hit' && <div className={`${styles.targetGroup} ${styles.hitGroup}`}><span className={styles.lock}><b>HIT!</b></span><img src={moleHitImage} alt="잡힌 두더지" /></div>}
      </div>;
    })}</div>
    {!ready && <p className={styles.connectionError} role="alert">연결 또는 화면 상태를 확인한 후 측정을 중단하고 다시 시도해주세요.</p>}
  </div>;
}
