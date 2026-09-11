import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { fetchDevices } from '../../api/devices';
import { fetchSettings, updateSettings } from '../../api/settings';
import { fetchStatus } from '../../api/status';
import DashboardGazeMeasurement from '../../components/dashboard/DashboardGazeMeasurement';
import DeviceSelector from '../../components/dashboard/DeviceSelector';
import { useGazeCalibrationStore } from '../../store/gazeCalibrationStore';
import { useSessionStore } from '../../store/sessionStore';
import { sendGazeCalibration, subscribeGazeCalibration } from '../../ws/gazeCalibration';
import styles from './GazeCalibrationPage.module.css';

const gradeLabels = { excellent: '우수', good: '양호', poor: '나쁨' };

export default function GazeCalibrationPage() {
  const navigate = useNavigate();
  const flow = useGazeCalibrationStore();
  const connected = useSessionStore((state) => state.wsConnected);
  const change = flow.change;
  const reset = flow.reset;
  const [settingsConfig, setSettingsConfig] = useState(null);
  const [cameras, setCameras] = useState([]);
  const [selectedCameraId, setSelectedCameraId] = useState('');
  const [devicesLoading, setDevicesLoading] = useState(true);
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
      calib_result: (result) => useGazeCalibrationStore.getState().receiveResult(result),
      calib_saved: (savedCalib) => change({ savedCalib, step: 'done', pending: false }),
      calib_denied: ({ message }) => change({ step: 'start', pending: false, error: message }),
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
    if (flow.step !== 'position' || !ready || !flow.point || !flow.precheck?.face || flow.precheck.distance !== 'ok' || flow.precheck.lighting !== 'ok') return undefined;
    const timer = setTimeout(() => change({ step: 'guide', pending: false, error: '' }), 500);
    return () => clearTimeout(timer);
  }, [change, flow.point?.n, flow.precheck?.distance, flow.precheck?.face, flow.precheck?.lighting, flow.step, ready]);

  useEffect(() => {
    if (!['measuring', 'stopConfirm'].includes(flow.step) && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }, [flow.step]);

  function send(type, data = {}, patch = {}) {
    try {
      sendGazeCalibration(type, data);
      change({ pending: true, error: '', ...patch });
    } catch (error) {
      change({ pending: false, error: error.message });
    }
  }

  async function start() {
    const selectedCamera = cameras.find((item) => item.id === selectedCameraId);
    if (!selectedCamera) { change({ error: '사용할 카메라를 선택해주세요.' }); return; }
    change({ pending: true, error: '' });
    try {
      let latest = settingsConfig ?? await fetchSettings();
      if (latest.settings.cameraDeviceId !== selectedCamera.id || latest.settings.cameraDevice !== selectedCamera.name) {
        latest = await updateSettings({
          settings: { ...latest.settings, cameraDeviceId: selectedCamera.id, cameraDevice: selectedCamera.name },
          updatedAt: latest.updatedAt,
        });
        setSettingsConfig(latest);
      }
      // TODO(BE): 보정 시작 시 저장된 cameraDeviceId를 Python Runtime 카메라 입력에 적용하는 경로 확인 필요
      send('calib_start', {}, {
        step: 'position', precheck: null, point: null, result: null, poorCount: 0,
        restartPending: false, savedCalib: null, delayed: false, failed: false,
      });
    } catch (error) {
      change({ pending: false, error: error.message });
    }
  }

  async function beginMeasurement() {
    change({ pending: true, error: '' });
    try {
      await document.documentElement.requestFullscreen();
      if (flow.restartPending) sendGazeCalibration('calib_restart');
      change({ step: 'measuring', pending: false, restartPending: false, failed: false, ...(flow.restartPending ? { point: null, result: null } : {}) });
    } catch (error) {
      change({ pending: false, error: error.message });
    }
  }

  function cancelAndReturn() {
    if (connected) {
      try { sendGazeCalibration('calib_cancel'); } catch { /* 연결 종료 시 화면 복귀 우선 */ }
    }
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    reset();
    navigate('/dashboard?view=gaze');
  }

  function openCameraSettings() {
    if (connected) {
      try { sendGazeCalibration('calib_cancel'); } catch { /* 설정 화면 이동 우선 */ }
    }
    navigate('/dashboard?view=settings');
  }

  const failMeasurement = useCallback((message) => change({ failed: true, pending: false, error: message }), [change]);
  const button = (label, action, disabled = false, primary = false) => <button className={primary ? styles.primary : ''} onClick={action} disabled={disabled || flow.pending}>{label}</button>;
  const footer = (children) => <footer className={styles.footer}>{children}</footer>;
  let content;

  if (flow.step === 'start') {
    content = <><h1>시선 설정</h1><div className={styles.center}><h2>시선 설정을 시작합니다</h2><div className={styles.icon}>◎</div><DeviceSelector label="카메라" devices={cameras} value={selectedCameraId} onChange={setSelectedCameraId} disabled={devicesLoading || flow.pending} /></div>{footer(button('시작하기', start, !ready || devicesLoading || !selectedCameraId, true))}</>;
  } else if (flow.step === 'position') {
    const valid = flow.precheck?.face && flow.precheck.distance === 'ok' && flow.precheck.lighting === 'ok' && flow.point;
    content = <><h1>위치 확인</h1><div className={styles.center}><p>앉아야 할 자리에 앉아주세요</p><p>화면을 정면으로 바라보고 바른 자세로 앉아주세요</p><p>서버 확인값 — 얼굴: {flow.precheck ? (flow.precheck.face ? '인식됨' : '미인식') : '확인 중'} · 거리: {flow.precheck?.distance ?? '확인 중'} · 조명: {flow.precheck?.lighting ?? '확인 중'}</p>{valid && <p role="status">위치 확인이 완료되었습니다. 측정 안내로 이동합니다.</p>}</div>{flow.delayed && <p role="status">위치 확인 응답이 지연되고 있습니다. AI 연결 상태를 확인해주세요.</p>}{footer(<>{button('취소', cancelAndReturn)}{button('다음', () => change({ step: 'guide', pending: false, error: '' }), !ready || !valid, true)}</>)}</>;
  } else if (flow.step === 'guide') {
    content = <div className={styles.center}><div className={styles.icon}>◎</div><h2>시선 측정을 {flow.restartPending ? '다시 할게요' : '시작하겠습니다'}</h2><p>화면에 튀어나오는 두더지의 코를 바라보면 됩니다.<br />약 1분 정도 걸립니다.</p><div className={styles.preview}>· 화면과 60~80cm 거리를 유지해주세요<br />· 보정 중에는 고개를 크게 움직이지 마세요<br />· 안경을 쓴다면 평소 사용하는 상태로 진행해주세요</div><div className={styles.actions}>{button('취소', cancelAndReturn)}{button('시작하기', beginMeasurement, !ready, true)}</div></div>;
  } else if (flow.step === 'measuring' || flow.step === 'stopConfirm') {
    content = <><DashboardGazeMeasurement point={flow.point} ready={ready} connected={connected} onFailure={failMeasurement} onCancel={() => change({ step: 'stopConfirm', pending: false })} />{flow.step === 'stopConfirm' && <div className={styles.backdrop}><section className={styles.modal} role="dialog" aria-modal="true"><div className={styles.modalIcon}>!</div><h2>보정을 그만둘까요?</h2><p>지금까지 측정한 시선 데이터는 저장되지 않습니다.<br />이전 시선 데이터가 그대로 유지됩니다.</p><div className={styles.actions}>{button('계속하기', () => change({ step: 'measuring', failed: false, error: '' }))}{button('그만두기', cancelAndReturn, false, true)}</div></section></div>}</>;
  } else if (flow.step === 'result') {
    const result = flow.result;
    const poor = result.grade === 'poor';
    const exhausted = poor && (flow.poorCount >= 3 || result.remeasuresLeft === 0);
    const extent = Math.max(100, ...(result.points ?? []).flatMap((point) => [Math.abs(point.dx), Math.abs(point.dy)])) * 1.2;
    content = <><h1>시선 학습 결과</h1><div className={styles.center}><div className={styles.plot}><svg viewBox={`${-extent} ${-extent} ${extent * 2} ${extent * 2}`} aria-label="목표점 기준 시선 오차 분포"><circle cx="0" cy="0" r={extent / 40} className={styles.target} />{result.points?.map((point) => <circle key={point.n} cx={point.dx} cy={point.dy} r={extent / 30} />)}</svg><p>점: 목표 지점 · 원: 실제 측정된 시선 위치 (오차)</p></div><h2>평균 오차 {result.avgErrorPx == null ? '미제공' : `${Math.round(result.avgErrorPx)}px`} · 최대 오차 {result.maxErrorPx == null ? '미제공' : `${Math.round(result.maxErrorPx)}px`}</h2><p>오차 범위: {gradeLabels[result.grade] ?? '미제공'}</p>{poor && <p>{exhausted ? '지속적으로 큰 오차가 발생하고 있습니다. 카메라 설정을 확인한 후 다시 측정해주십시오.' : '오차가 다소 큽니다. 시선을 다시 측정해주세요.'}</p>}</div>{footer(<>{exhausted ? button('카메라 설정', openCameraSettings) : button('다시 측정', () => change({ step: 'guide', restartPending: true, pending: false, error: '' }), !ready || !result.remeasuresLeft)}{!poor && button('계속 진행', () => send('calib_commit'), !ready || result.pass !== true, true)}</>)}</>;
  } else {
    content = <><h1>시선 설정</h1><div className={styles.center}><div className={styles.icon}>✓</div><h2>시선 설정 완료!</h2><p>시선 학습이 완료되었습니다</p></div>{footer(button('다음', () => navigate('/dashboard?view=gaze', { state: { gazeAdded: flow.savedCalib } }), false, true))}</>;
  }

  return <main className={styles.page}><section className={styles.card}>{content}{flow.pending && <p role="status">서버 응답을 기다리고 있습니다.</p>}{flow.error && <p className={styles.error} role="alert">{flow.error}</p>}</section><p className={styles.connection}>실시간 연결: {connected ? '연결됨' : '대기 중'} · AI: {flow.status?.agentConnected ? '연결됨' : '대기 중'}</p></main>;
}
