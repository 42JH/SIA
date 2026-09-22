import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { fetchDevices } from '../../api/devices';
import { fetchSettings, updateSettings } from '../../api/settings';
import { fetchStatus } from '../../api/status';
import DashboardGazeMeasurement from '../../components/dashboard/DashboardGazeMeasurement';
import { useGazeCalibrationStore } from '../../store/gazeCalibrationStore';
import { useSessionStore } from '../../store/sessionStore';
import { sendGazeCalibration, subscribeGazeCalibration } from '../../ws/gazeCalibration';
import { startGesturePreview, stopGesturePreview, subscribeGestures } from '../../ws/gestures';
import siaLogo from '../../assets/sia-logo.png';
import styles from './GazeCalibrationPage.module.css';

const gradeLabels = { excellent: '우수', good: '양호', poor: '나쁨' };
const GRADE_EXCELLENT_PX = 160;
const GRADE_GOOD_PX = 250;

function precheckLabel(value, okWhen) {
  if (value == null || value === '-') return '확인 중';
  if (okWhen(value)) return '✓';
  if (typeof value === 'string' && value !== 'ok') return value;
  return '확인 필요';
}

export default function GazeCalibrationPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const flow = useGazeCalibrationStore();
  const connected = useSessionStore((state) => state.wsConnected);
  const change = flow.change;
  const reset = flow.reset;
  const autoStarted = useRef(false);
  const previewSeq = useRef(-1);
  const previewImg = useRef(null);
  const stopOpenRef = useRef(false);
  const heldResultRef = useRef(null);
  const completionResultRef = useRef(null);
  const [settingsConfig, setSettingsConfig] = useState(null);
  const [cameras, setCameras] = useState([]);
  const [selectedCameraId, setSelectedCameraId] = useState('');
  const [devicesLoading, setDevicesLoading] = useState(true);
  const [cameraPreviewFrame, setCameraPreviewFrame] = useState(null);
  const [cameraPreviewReady, setCameraPreviewReady] = useState(false);
  const [cameraPreviewError, setCameraPreviewError] = useState('');
  const [stopOpen, setStopOpen] = useState(false);
  const [finishingMeasurement, setFinishingMeasurement] = useState(false);
  const ready = connected && flow.status?.agentConnected && !flow.failed;

  useEffect(() => {
    let disposed = false;
    Promise.all([fetchSettings(), fetchDevices()]).then(([nextSettings, nextDevices]) => {
      if (disposed) return;
      setSettingsConfig(nextSettings);
      setCameras(nextDevices.cameras);
      const configured = nextDevices.cameras.find((item) => nextSettings.settings.cameraDeviceId ? item.id === nextSettings.settings.cameraDeviceId : item.name === nextSettings.settings.cameraDevice);
      setSelectedCameraId((configured ?? nextDevices.cameras.find((item) => item.isDefault) ?? nextDevices.cameras[0])?.id ?? '');
    }).catch((error) => { if (!disposed) change({ error: error.message }); })
      .finally(() => { if (!disposed) setDevicesLoading(false); });
    return () => { disposed = true; };
  }, [change]);

  useEffect(() => {
    reset();
    let disposed = false;
    let pollTimer;
    async function poll() {
      try {
        const status = await fetchStatus();
        if (!disposed) change({ status });
      } catch (error) {
        if (!disposed) change({ error: error.message });
      }
      if (!disposed) pollTimer = setTimeout(poll, 3000);
    }
    poll();
    const unsubscribe = subscribeGazeCalibration({
      __connection__: ({ status }) => { if (status === 'closed') change({ failed: true, pending: false, error: '실시간 연결이 끊겼습니다.' }); },
      agent_status: ({ connected: agentConnected }) => change({ status: { ...useGazeCalibrationStore.getState().status, agentConnected }, ...(!agentConnected ? { failed: true, pending: false, error: 'AI 연결이 끊겼습니다.' } : {}) }),
      settings_sync: (data) => change({ status: { ...useGazeCalibrationStore.getState().status, ...data } }),
      calib_precheck: (precheck) => change({ precheck, delayed: false, pending: false }),
      calib_point: (point) => change({ point, pending: false }),
      calib_result: (result) => {
        if (stopOpenRef.current) heldResultRef.current = result;
        else if (useGazeCalibrationStore.getState().step === 'measuring') {
          completionResultRef.current = result;
          setFinishingMeasurement(true);
          change({ pending: false });
        } else useGazeCalibrationStore.getState().receiveResult(result);
      },
      calib_saved: (savedCalib) => change({ savedCalib, step: 'done', pending: false }),
      calib_denied: ({ message }) => { autoStarted.current = false; change({ step: 'start', pending: false, error: message }); },
      calib_limit: ({ message }) => {
        const current = useGazeCalibrationStore.getState().result;
        change({ pending: false, error: message, result: current ? { ...current, remeasuresLeft: 0 } : current });
      },
      error: ({ message, of }) => { if (of?.startsWith('calib_')) change({ pending: false, error: message }); },
    });
    return () => { disposed = true; clearTimeout(pollTimer); unsubscribe(); };
  }, [change, reset]);

  useEffect(() => {
    if (flow.step !== 'position' || flow.precheck) return undefined;
    const timer = setTimeout(() => change({ delayed: true }), 8000);
    return () => clearTimeout(timer);
  }, [change, flow.precheck, flow.step]);

  useEffect(() => {
    if (flow.step !== 'position' || !connected) return undefined;
    let cancelled = false;
    let retryTimer;
    const requestStart = () => {
      if (cancelled) return;
      try {
        startGesturePreview();
      } catch (error) {
        setCameraPreviewReady(false);
        setCameraPreviewError(error.message);
        retryTimer = setTimeout(requestStart, 1200);
      }
    };
    const unsubscribe = subscribeGestures({
      cam_preview_state: (data) => {
        if (cancelled) return;
        if (data.phase === 'READY') {
          setCameraPreviewReady(true);
          setCameraPreviewError('');
        } else if (data.phase === 'ERROR') {
          setCameraPreviewReady(false);
          setCameraPreviewError(data.message || 'AI 카메라 화면을 불러올 수 없습니다.');
          previewSeq.current = -1;
          clearTimeout(retryTimer);
          retryTimer = setTimeout(requestStart, 700);
        }
      },
      cam_preview_frame: (data) => {
        if (cancelled || !data.jpegB64) return;
        const seq = Number(data.seq);
        if (!Number.isInteger(seq) || seq < 0 || seq <= previewSeq.current) return;
        previewSeq.current = seq;
        const src = `data:image/jpeg;base64,${data.jpegB64}`;
        if (previewImg.current) previewImg.current.src = src;
        setCameraPreviewReady(true);
        setCameraPreviewError('');
        setCameraPreviewFrame((current) => current || src);
      },
      error: (data) => {
        if (cancelled || data.of !== 'cam_preview_start') return;
        setCameraPreviewReady(false);
        setCameraPreviewError(data.message || 'AI 카메라 화면을 불러올 수 없습니다.');
        previewSeq.current = -1;
        clearTimeout(retryTimer);
        retryTimer = setTimeout(requestStart, 1200);
      },
    });
    requestStart();
    return () => {
      cancelled = true;
      clearTimeout(retryTimer);
      unsubscribe();
      try { stopGesturePreview(); } catch { /* 연결 종료 시 별도 처리 없음 */ }
      previewSeq.current = -1;
    };
  }, [connected, flow.step]);

  useEffect(() => {
    if (flow.step === 'measuring') return;
    window.scrollTo({ top: 0, left: 0, behavior: 'instant' });
  }, [flow.step]);

  useEffect(() => {
    if (flow.step !== 'measuring' && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }, [flow.step]);

  useEffect(() => {
    if (flow.step !== 'start' || devicesLoading || !ready || !selectedCameraId || autoStarted.current) return;
    autoStarted.current = true;
    start();
  }, [devicesLoading, flow.step, ready, selectedCameraId]);

  function send(type, data = {}, patch = {}) {
    try {
      sendGazeCalibration(type, data);
      change({ pending: true, error: '', ...patch });
    } catch (error) { change({ pending: false, error: error.message }); }
  }

  async function start() {
    const selectedCamera = cameras.find((item) => item.id === selectedCameraId);
    if (!selectedCamera) { autoStarted.current = false; change({ error: '사용할 카메라를 선택해주세요.' }); return; }
    change({ pending: true, error: '' });
    try {
      let latest = settingsConfig ?? await fetchSettings();
      if (latest.settings.cameraDeviceId !== selectedCamera.id || latest.settings.cameraDevice !== selectedCamera.name) {
        latest = await updateSettings({ settings: { ...latest.settings, cameraDeviceId: selectedCamera.id, cameraDevice: selectedCamera.name }, updatedAt: latest.updatedAt });
        setSettingsConfig(latest);
      }
      // TODO(BE): 보정 시작 시 저장된 cameraDeviceId를 Python Runtime 카메라 입력에 적용하는 경로 확인 필요
      completionResultRef.current = null;
      setFinishingMeasurement(false);
      send('calib_start', {}, { step: 'position', precheck: null, point: null, result: null, poorCount: 0, restartPending: false, savedCalib: null, delayed: false, failed: false });
    } catch (error) {
      autoStarted.current = false;
      change({ pending: false, error: error.message });
    }
  }

  async function beginMeasurement() {
    change({ pending: true, error: '' });
    try {
      await document.documentElement.requestFullscreen();
      if (flow.restartPending) sendGazeCalibration('calib_restart');
      completionResultRef.current = null;
      setFinishingMeasurement(false);
      change({ step: 'measuring', pending: false, restartPending: false, failed: false, ...(flow.restartPending ? { point: null, result: null } : {}) });
    } catch (error) { change({ pending: false, error: error.message }); }
  }

  function cancelAndReturn() {
    stopOpenRef.current = false;
    heldResultRef.current = null;
    setStopOpen(false);
    if (connected) { try { sendGazeCalibration('calib_cancel'); } catch { /* 연결 종료 시 화면 복귀 우선 */ } }
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    reset();
    navigate('/dashboard?view=gaze', { state: location.state });
  }

  function openStopConfirm() {
    stopOpenRef.current = true;
    setStopOpen(true);
  }

  function continueMeasurement() {
    stopOpenRef.current = false;
    setStopOpen(false);
    if (heldResultRef.current) {
      const result = heldResultRef.current;
      heldResultRef.current = null;
      completionResultRef.current = result;
      setFinishingMeasurement(true);
    }
  }

  const finishMeasurementVisual = useCallback(() => {
    const result = completionResultRef.current;
    if (!result) return;
    completionResultRef.current = null;
    setFinishingMeasurement(false);
    useGazeCalibrationStore.getState().receiveResult(result);
  }, []);

  function openCameraSettings() {
    if (connected) { try { sendGazeCalibration('calib_cancel'); } catch { /* 설정 화면 이동 우선 */ } }
    navigate('/dashboard?view=settings', { state: { dashboardHistory: [...(Array.isArray(location.state?.dashboardHistory) ? location.state.dashboardHistory : []), 'gaze'] } });
  }

  const failMeasurement = useCallback((message) => change({ failed: true, pending: false, error: message }), [change]);
  const validPosition = Boolean(flow.precheck?.face && flow.precheck.distance === 'ok' && flow.precheck.lighting === 'ok');
  const nextGuide = () => change({ step: 'guide', pending: false, error: '' });
  let content;

  if (flow.step === 'start') {
    content = <CalibrationShell title="시선 보정" subtitle="시선 보정을 준비하고 있습니다."><div className={styles.preparing}><span className={styles.spinner} /><h2>카메라와 AI 연결을 확인하고 있습니다</h2><p>{selectedCameraId ? '잠시만 기다려주세요.' : '사용 가능한 카메라를 확인해주세요.'}</p><button onClick={openStopConfirm}>취소</button></div></CalibrationShell>;
  } else if (flow.step === 'position') {
    content = <CalibrationShell title="위치 확인"><section className={`${styles.techFrame} ${styles.positionFrame}`}>{<><img ref={previewImg} className={styles.cameraPreview} alt="AI 카메라 미리보기" hidden={!cameraPreviewFrame} />{!cameraPreviewFrame && <span className={styles.cameraWaiting}>{cameraPreviewReady ? '카메라 화면을 기다리고 있습니다.' : 'AI 카메라를 준비하고 있습니다.'}</span>}</>}<div className={styles.cameraShade} /><FrameMarks /><div className={styles.cornerMarks}><i /><i /><i /><i /></div><strong>화면 중앙에 바른 자세로 앉아주세요.</strong>{cameraPreviewError && <p className={styles.cameraError}>{cameraPreviewError}</p>}</section><div className={styles.positionFooter}><p>얼굴 {precheckLabel(flow.precheck?.face, (value) => value === true)} · 거리 {precheckLabel(flow.precheck?.distance, (value) => value === 'ok')} · 조명 {precheckLabel(flow.precheck?.lighting, (value) => value === 'ok')}</p><div><button onClick={openStopConfirm}>취소</button><button onClick={nextGuide} disabled={!ready || !validPosition}>다음</button></div></div>{flow.delayed && <p className={styles.inlineError}>위치 확인 응답이 지연되고 있습니다. AI 연결 상태를 확인해주세요.</p>}</CalibrationShell>;
  } else if (flow.step === 'guide') {
    content = <CalibrationShell title="시선 보정"><section className={styles.guideFrame}><EyeIcon /><h2>시선 측정을 다시 할게요</h2><p>화면이 밝아 보이도록 디스플레이를 조정하면 됩니다.<br />약 1분 정도 걸립니다.</p><div className={styles.tipBox}><strong>• 화면 중앙에 바른 자세로 앉아주세요.</strong><strong>• 너무 멀거나 가깝지 않게, 얼굴이 선명히 보이도록 앉아주세요.</strong><strong>• 조명이 너무 어둡거나 밝지 않은 곳에서 진행해주세요.</strong><strong>• 안경을 벗으면 평소 사용하는 상태로 진행해주세요.</strong></div><div className={styles.guideActions}><button onClick={openStopConfirm}>취소</button><button className={styles.primary} onClick={beginMeasurement} disabled={!ready}>시작하기</button></div></section></CalibrationShell>;
  } else if (flow.step === 'measuring') {
    content = <DashboardGazeMeasurement point={flow.point} ready={ready} connected={connected} finishing={finishingMeasurement} onFailure={failMeasurement} onCancel={openStopConfirm} onVisualComplete={finishMeasurementVisual} />;
  } else if (flow.step === 'result') {
    const result = flow.result;
    const errors = (result.points ?? []).map((point) => Math.hypot(Number(point.dx), Number(point.dy))).filter(Number.isFinite);
    const minError = result.minErrorPx ?? (errors.length ? Math.min(...errors) : null);
    const displayGrade = result.avgErrorPx == null ? '미제공' : (gradeLabels[result.grade] ?? (result.avgErrorPx < GRADE_EXCELLENT_PX ? '우수' : result.avgErrorPx < GRADE_GOOD_PX ? '양호' : '나쁨'));
    const poor = result.pass !== true;
    const exhausted = poor && (flow.poorCount >= 3 || result.remeasuresLeft === 0);
    content = <CalibrationShell title="시선 학습 결과" subtitle="측정된 시선과 목표 위치의 차이를 확인해보세요."><section className={styles.resultFrame}><h2>시선 학습 결과</h2><ResultPlot result={result} /><div className={styles.resultCopy}><small>○ 목표 지점&nbsp;&nbsp; ● 실제 측정된 시선 위치 (오차)</small><strong>최소 오차 {minError == null ? '미제공' : `${Math.round(minError)}px`} · 평균 오차 {result.avgErrorPx == null ? '미제공' : `${Math.round(result.avgErrorPx)}px`} · 최대 오차 {result.maxErrorPx == null ? '미제공' : `${Math.round(result.maxErrorPx)}px`}</strong><b className={poor ? styles.badGrade : ''}>오차 범위 · {displayGrade}</b><p>{exhausted ? '지속적으로 큰 오차가 발생하고 있습니다.' : poor ? '오차가 다소 큽니다. 시선을 다시 측정해주세요.' : '측정이 완료되었습니다.'}</p></div><div className={styles.resultActions}>{exhausted ? <button className={styles.primary} onClick={openCameraSettings}>카메라 설정</button> : poor ? <button onClick={() => change({ step: 'guide', restartPending: true, pending: false, error: '' })} disabled={!ready || !result.remeasuresLeft}>다시 측정</button> : <button onClick={() => send('calib_commit')} disabled={!ready || result.pass !== true}>계속 진행</button>}</div></section></CalibrationShell>;
  } else {
    content = <CalibrationShell title="시선 설정" subtitle="시선 학습이 완료되었습니다."><section className={styles.completeFrame}><span className={styles.completeIcon}>✓</span><h2>시선 설정 완료!</h2><p>시선 학습이 완료되었습니다</p><button className={styles.primary} onClick={() => navigate('/dashboard?view=gaze', { state: { ...(location.state ?? {}), gazeAdded: flow.savedCalib } })}>다음</button></section></CalibrationShell>;
  }

  return <main className={styles.page}>{content}{stopOpen && <ConfirmModal title="보정을 그만둘까요?" description={<>지금까지 측정한 시선 데이터는 저장되지 않습니다.<br />이전 시선 데이터가 그대로 유지됩니다.</>} secondary="계속하기" primary="그만두기" onSecondary={continueMeasurement} onPrimary={cancelAndReturn} />}{flow.pending && flow.step !== 'start' && <p className={styles.status} role="status">서버 응답을 기다리고 있습니다.</p>}{flow.error && <p className={styles.error} role="alert">{flow.error}</p>}</main>;
}

function CalibrationShell({ title, subtitle = '', children }) {
  return <><header className={styles.topbar}><img src={siaLogo} alt="SIA" /></header><section className={styles.shell}><div className={styles.pageTitle}><div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div><span>SMART INTERACTION ASSISTANT<i /></span></div>{children}</section></>;
}

function FrameMarks() { return <i className={styles.frameLine} />; }

function EyeIcon() { return <span className={styles.eyeIcon}><svg viewBox="0 0 80 80" aria-hidden="true"><circle cx="40" cy="40" r="34" /><path d="M20 40s8-11 20-11 20 11 20 11-8 11-20 11S20 40 20 40Z" /><circle cx="40" cy="40" r="6" /></svg></span>; }

function ConfirmModal({ title, description, secondary, primary, onSecondary, onPrimary }) {
  return <div className={styles.backdrop}><section className={`${styles.modal}`} role="dialog" aria-modal="true"><FrameMarks /><span className={styles.modalIcon}>!</span><h2>{title}</h2><p>{description}</p><div><button onClick={onSecondary}>{secondary}</button><button className={styles.primary} onClick={onPrimary}>{primary}</button></div></section></div>;
}

function ResultPlot({ result }) {
  const points = result.points ?? [];
  const maxError = Math.max(40, ...points.flatMap((point) => [Math.abs(Number(point.dx) || 0), Math.abs(Number(point.dy) || 0)]));
  const scale = 36 / maxError;
  return <div className={styles.plot}><svg viewBox="-170 -130 340 260" preserveAspectRatio="xMidYMid meet" aria-label="목표점 기준 시선 오차 분포"><circle className={styles.guideCircle} cx="0" cy="0" r="58" />{points.map((point) => {
    const column = (point.n - 1) % 3 - 1;
    const row = Math.floor((point.n - 1) / 3) - 1;
    const targetX = column * 46;
    const targetY = row * 34;
    const measuredX = targetX + Number(point.dx) * scale;
    const measuredY = targetY + Number(point.dy) * scale;
    return <g key={point.n}><circle className={styles.targetPoint} cx={targetX} cy={targetY} r="7" /><line x1={targetX} y1={targetY} x2={measuredX} y2={measuredY} /><circle className={styles.measuredPoint} cx={measuredX} cy={measuredY} r="5" /></g>;
  })}<circle className={styles.plotCenter} cx="0" cy="0" r="8" /></svg></div>;
}
