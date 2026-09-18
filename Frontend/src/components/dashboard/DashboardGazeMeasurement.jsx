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
    const escape = (event) => { if (event.key === 'Escape' && document.fullscreenElement) onCancel(); };
    document.addEventListener('keydown', escape);
    return () => document.removeEventListener('keydown', escape);
  }, [onCancel]);

  useEffect(() => {
    if (!introDone) return undefined;
    if (!document.fullscreenElement) {
      onFailure('전체화면이 해제되었습니다. 측정을 중단한 뒤 다시 시도해주세요.');
      return undefined;
    }
    const check = () => { if (!document.fullscreenElement) onFailure('전체화면이 해제되었습니다. 측정을 중단한 뒤 다시 시도해주세요.'); };
    let resizeGuardReady = false;
    let measuredWidth = window.innerWidth;
    let measuredHeight = window.innerHeight;
    const guardTimer = setTimeout(() => {
      measuredWidth = window.innerWidth;
      measuredHeight = window.innerHeight;
      resizeGuardReady = true;
    }, 1200);
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
  }, [introDone, onFailure]);

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
    setActivePoint(null);
    setHitPoint(previous);
    clearTimeout(transitionTimer.current);
    transitionTimer.current = setTimeout(() => {
      setCaught((items) => new Set(items).add(previous));
      displayedPoint.current = point.n;
      setHitPoint(null);
      setActivePoint(point.n);
    }, 420);
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
        {state === 'active' && <div className={styles.targetGroup}><img src={moleImage} alt="두더지" /><span className={styles.lock}><i /><b>1초</b></span><span ref={target} className={styles.noseAnchor} aria-hidden="true" /></div>}
        {state === 'hit' && <div className={`${styles.targetGroup} ${styles.hitGroup}`}><img src={moleHitImage} alt="잡힌 두더지" /><span className={styles.lock}><i /><b>HIT!</b></span></div>}
      </div>;
    })}</div>
    {!introDone && <div className={styles.startBackdrop}><section className={styles.startModal} role="dialog" aria-modal="true"><span>◎</span><h2>두더지 잡기를 시작할까요?</h2><p>시작 버튼을 누른 뒤 나타나는 두더지의 코를 바라보세요.</p><div><button onClick={onCancel}>취소</button><button className={styles.startPrimary} onClick={() => setIntroDone(true)} disabled={!ready}>시작하기</button></div></section></div>}
    {!ready && <p className={styles.connectionError} role="alert">연결 또는 화면 상태를 확인한 후 측정을 중단하고 다시 시도해주세요.</p>}
  </div>;
}
