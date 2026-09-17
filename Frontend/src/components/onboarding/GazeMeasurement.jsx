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
    const timer = setTimeout(() => setIntroDone(true), 1500); // 추정값 - 원본 이미지에서 명확히 확인 불가
    return () => clearTimeout(timer);
  }, []);

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
    // 추정값 - 원본 이미지에서 명확히 확인 불가
    const timer = setTimeout(() => {
      setCaught((items) => new Set(items).add(previous));
      displayedPoint.current = point.n;
      setRecentlyHit(null);
      setActivePoint(point.n);
    }, 420);
    return () => clearTimeout(timer);
  }, [introDone, point]);
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
    if (!activePoint || !ready || !document.fullscreenElement || !target.current || sentPoints.current.has(activePoint)) return;
    const frame = requestAnimationFrame(() => {
      const rect = target.current.getBoundingClientRect();
      try {
        sendOnboarding('calib_point_shown', { n: activePoint, x: Math.round((rect.x + rect.width / 2) * window.devicePixelRatio), y: Math.round((rect.y + rect.height / 2) * window.devicePixelRatio) });
        sentPoints.current.add(activePoint);
      }
      catch (error) { fail(error.message); }
    });
    return () => cancelAnimationFrame(frame);
  }, [activePoint, ready]);
  const screen = <div className={styles.measure}><p className={styles.guide}>튀어나온 두더지의 코를 1초간 바라보면 잡힙니다.</p><div className={styles.grid}>{Array.from({ length: 9 }, (_, index) => {
    const number = index + 1;
    const active = activePoint === number;
    const isCaught = caught.has(number);
    const hit = recentlyHit === number;
    return <div className={styles.cell} key={number}><div className={`${styles.platform} ${active ? styles.active : ''} ${isCaught ? styles.caught : ''} ${hit ? styles.hit : ''}`}>{active && <><span ref={target} className={styles.nose}>●</span><span className={styles.timer}>1초</span><img src={moleImage} alt="시선으로 잡을 두더지" /></>}{isCaught && !hit && <span className={styles.check}>✓</span>}{hit && <><span className={styles.hitLabel}>HIT!</span><img src={moleHitImage} alt="잡은 두더지" /></>}</div><small>{isCaught && !hit ? '잡음' : active || hit ? '' : '대기'}</small></div>;
  })}</div>{!ready && <p className={styles.measureError} role="alert">연결 또는 화면 상태를 확인해주세요.</p>}</div>;
  return createPortal(screen, document.body);
}
