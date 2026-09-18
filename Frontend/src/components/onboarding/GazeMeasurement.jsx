import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { sendOnboarding } from '../../ws/onboarding';
import { useOnboardingStore } from '../../store/onboardingStore';
import moleImage from '../../assets/gaze-mole.png';
import moleHitImage from '../../assets/gaze-mole-hit.png';
import styles from './GazeMeasurement.module.css';

export default function GazeMeasurement({ point, ready }) {
  const target = useRef(null);
  const sentPoints = useRef(new Set());
  const displayedPoint = useRef(null);
  const [introDone, setIntroDone] = useState(false);
  const [activePoint, setActivePoint] = useState(null);
  const [caught, setCaught] = useState(() => new Set());
  const [recentlyHit, setRecentlyHit] = useState(null);
  const fail = (error) => useOnboardingStore.getState().interrupt(error);

  useEffect(() => {
    if (!introDone || !point?.n) return undefined;
    if (!Number.isInteger(point.n) || point.n < 1 || point.n > 9) {
      fail('시선 측정 지점 번호가 올바르지 않습니다. 연결 상태를 확인해주세요.');
      return undefined;
    }
    const previous = displayedPoint.current;
    if (!previous) {
      displayedPoint.current = point.n;
      setActivePoint(point.n);
      return undefined;
    }
    if (previous === point.n) return undefined;
    setActivePoint(null);
    setRecentlyHit(previous);
    const timer = setTimeout(() => {
      setCaught((items) => new Set(items).add(previous));
      displayedPoint.current = point.n;
      setRecentlyHit(null);
      setActivePoint(point.n);
    }, 420);
    return () => clearTimeout(timer);
  }, [introDone, point]);

  useEffect(() => {
    if (!introDone) return undefined;
    if (!document.fullscreenElement) {
      fail('전체화면이 해제되었습니다. 보정을 다시 시작해주세요.');
      return undefined;
    }
    const check = () => { if (!document.fullscreenElement) fail('전체화면이 해제되었습니다. 보정을 다시 시작해주세요.'); };
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
      fail('화면 크기가 변경되었습니다. 보정을 다시 시작해주세요.');
    };
    document.addEventListener('fullscreenchange', check);
    window.addEventListener('resize', resized);
    return () => {
      clearTimeout(guardTimer);
      document.removeEventListener('fullscreenchange', check);
      window.removeEventListener('resize', resized);
    };
  }, [introDone]);

  useEffect(() => {
    if (!activePoint || !ready || !document.fullscreenElement || !target.current || sentPoints.current.has(activePoint)) return;
    let secondFrame;
    const firstFrame = requestAnimationFrame(() => {
      secondFrame = requestAnimationFrame(() => {
        const rect = target.current?.getBoundingClientRect();
        if (!rect) return;
        try {
          sendOnboarding('calib_point_shown', { n: activePoint, x: Math.round((rect.left + rect.width / 2) * window.devicePixelRatio), y: Math.round((rect.top + rect.height / 2) * window.devicePixelRatio) });
          sentPoints.current.add(activePoint);
        } catch (error) { fail(error.message); }
      });
    });
    return () => { cancelAnimationFrame(firstFrame); cancelAnimationFrame(secondFrame); };
  }, [activePoint, ready]);

  const screen = <div className={styles.measure}>
    <p className={styles.guide}>튀어나온 두더지의 코를 1초간 바라보면 잡힙니다.</p>
    <div className={styles.grid}>{Array.from({ length: 9 }, (_, index) => {
      const number = index + 1;
      const active = activePoint === number;
      const hit = recentlyHit === number;
      const isCaught = caught.has(number) && !hit;
      return <div className={styles.cell} key={number}>
        <span className={styles.hole} aria-hidden="true" />
        {isCaught && <><span className={styles.check}>✓</span><small>잡음</small></>}
        {!active && !hit && !isCaught && <small>대기</small>}
        {active && <div className={styles.targetGroup}><img src={moleImage} alt="시선으로 잡을 두더지" /><span className={styles.scope}><i /><b>1초</b></span><span ref={target} className={styles.noseAnchor} aria-hidden="true" /></div>}
        {hit && <div className={`${styles.targetGroup} ${styles.hitGroup}`}><img className={styles.hitMole} src={moleHitImage} alt="잡은 두더지" /><span className={styles.scope}><i /><b>HIT!</b></span></div>}
      </div>;
    })}</div>
    {!introDone && <div className={styles.startBackdrop}><section className={styles.startModal} role="dialog" aria-modal="true"><b className={styles.modalBevel} /><h2>두더지 잡기를 시작할까요?</h2><p>시작하면 나타나는 두더지의 코를 1초간 바라보세요.</p><button onClick={() => setIntroDone(true)} disabled={!ready}>시작하기</button></section></div>}
    {!ready && <p className={styles.measureError} role="alert">연결 또는 화면 상태를 확인해주세요.</p>}
  </div>;
  return createPortal(screen, document.body);
}
