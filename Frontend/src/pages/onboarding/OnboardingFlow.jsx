import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { fetchSettings, updateSettings } from '../../api/settings';
import { fetchDevices } from '../../api/devices';
import { registerInstalledApps } from '../../api/onboarding';
import { sendOnboarding } from '../../ws/onboarding';
import { useSessionStore } from '../../store/sessionStore';
import { useOnboardingStore } from '../../store/onboardingStore';
import { useOnboarding } from './useOnboarding';
import GazeMeasurement from '../../components/onboarding/GazeMeasurement';
import VoiceEnrollment from '../../components/onboarding/VoiceEnrollment';
import styles from './OnboardingHome.module.css';

import { ENROLLMENT_SENTENCES as sentences, WAKE_SAMPLE_SECONDS } from './enrollmentConstants';

export default function OnboardingFlow() {
  useOnboarding();
  const location = useLocation();
  const navigate = useNavigate();
  const f = useOnboardingStore();
  const connected = useSessionStore((s) => s.wsConnected);
  const [config, setConfig] = useState(null);
  const [devices, setDevices] = useState({ mics: [], cameras: [] });
  const name = '시아야';
  const [mic, setMic] = useState('');
  const [camera, setCamera] = useState('');
  const [cameraSettingsOnly, setCameraSettingsOnly] = useState(false);
  const flowMode = new URLSearchParams(location.search).get('mode');
  const isMicOnly = flowMode === 'mic';
  const isCameraOnly = flowMode === 'camera';
  const deviceChange = location.state?.deviceChange;

  const ready = connected && f.status?.agentConnected && !f.interrupted;
  const change = f.change;
  useEffect(() => {
    const requestedStep = new URLSearchParams(window.location.search).get('step');
    if (requestedStep === 'micStart' || requestedStep === 'gazeStart') {
      change({
        step: requestedStep, pending: false, error: '', interrupted: false, request: null,
        ...(requestedStep === 'micStart' ? {
          wake: { n: 0, total: 5 }, wakeDone: false, voiceTempId: null,
          voiceSentence: null, voiceCompleted: 0, voiceResult: null, finalVoiceReview: null,
        } : {
          precheck: null, point: null, result: null, poorCount: 0,
          gazeWaitingSince: null, gazeDelayed: false,
        }),
      });
    }
  }, [change]);
  const go = (step) => change({ step, pending: false, error: '' });
  const label = (id, kind) => devices[kind].find((d) => d.id === id)?.name ?? null;
  const selectedDeviceLabel = (kind) => deviceChange?.kind === kind ? deviceChange.deviceName : label(kind === 'mic' ? mic : camera, `${kind === 'mic' ? 'mic' : 'camera'}s`);
  async function finishDeviceChange(kind) {
    await run(async () => {
      const latest = await fetchSettings();
      const key = kind === 'mic' ? 'mic' : 'camera';
      await updateSettings({
        settings: { ...latest.settings, [`${key}Device`]: deviceChange?.deviceName ?? null, [`${key}DeviceId`]: deviceChange?.deviceId ?? null },
        updatedAt: latest.updatedAt,
      });
      change({ step: 'welcome', pending: false, interrupted: false });
      navigate('/dashboard?view=settings');
    });
  }
  function cancelMicEnrollment() {
    if (f.voiceTempId && connected) {
      try { sendOnboarding('voice_reg_cancel', { tempId: f.voiceTempId }); } catch (error) { change({ error: error.message }); }
    }
    change({ step: 'welcome', pending: false, interrupted: true, request: null });
    navigate('/dashboard?view=settings');
  }
  async function run(action) {
    change({ pending: true, error: '' });
    try { await action(); } catch (error) { change({ pending: false, error: error.message }); }
  }
  function send(type, data = {}, patch = {}) {
    try {
      sendOnboarding(type, data);
      change({ pending: true, error: '', ...patch });
    }
    catch (error) { change({ pending: false, error: error.message }); }
  }
  async function basic() {
    go('basic');
    await run(async () => {
      const [settingsResult, devicesResult] = await Promise.allSettled([fetchSettings(), fetchDevices()]);
      if (devicesResult.status === 'fulfilled') setDevices(devicesResult.value);
      if (settingsResult.status === 'fulfilled') {
        const data = settingsResult.value;
        setConfig(data);
        if (devicesResult.status === 'fulfilled') {
          setMic(devicesResult.value.mics.find((d) => data.settings.micDeviceId ? d.id === data.settings.micDeviceId : d.name === data.settings.micDevice)?.id ?? '');
          setCamera(devicesResult.value.cameras.find((d) => data.settings.cameraDeviceId ? d.id === data.settings.cameraDeviceId : d.name === data.settings.cameraDevice)?.id ?? '');
        }
      }
      if (settingsResult.status === 'rejected') throw settingsResult.reason;
      if (devicesResult.status === 'rejected') throw devicesResult.reason;
      change({ pending: false });
    });
  }
  async function discover() {
    await run(async () => {
      const list = await fetchDevices();
      setDevices(list);
      setMic((current) => list.mics.some((d) => d.id === current) ? current : '');
      setCamera((current) => list.cameras.some((d) => d.id === current) ? current : '');
      change({ pending: false });
    });
  }
  async function save() {
    await run(async () => {
      try { setConfig(await updateSettings({ settings: { ...config.settings, wakeWord: name, micDevice: label(mic, 'mics'), micDeviceId: mic || null, cameraDevice: label(camera, 'cameras'), cameraDeviceId: camera || null }, updatedAt: config.updatedAt })); }
      catch (error) { if (error.code === 'SETTINGS_STALE') setConfig(await fetchSettings()); throw error; }
      // TODO(BE): 설정 저장 응답만으로 AI의 실제 카메라 전환을 확인할 수 없어 장치 적용 확인 계약 필요
      if (cameraSettingsOnly) { setCameraSettingsOnly(false); go('gazeStart'); }
      else { await registerInstalledApps(); go('micStart'); }
    });
  }
  function cameraSettings() {
    try {
      sendOnboarding('calib_cancel');
      change({ interrupted: false, precheck: null, point: null, result: null, gazeWaitingSince: null, gazeDelayed: false });
      setCameraSettingsOnly(true);
      basic();
    } catch (error) { change({ error: error.message, pending: false }); }
  }
  async function measure(restart = false) {
    await run(async () => {
      await document.documentElement.requestFullscreen();
      if (restart) sendOnboarding('calib_restart');
      change({ step: 'measuring', pending: false, ...(restart ? { point: null, result: null } : {}) });
    });
  }
  useEffect(() => {
    if (f.step !== 'measuring' && document.fullscreenElement) document.exitFullscreen().catch(() => {});
  }, [f.step]);
  const btn = (text, action, disabled = false) => <button onClick={action} disabled={disabled || f.pending}>{text}</button>;
  const foot = (children) => <footer className={styles.footer}>{children}</footer>;
  const center = (children) => <div className={styles.center}>{children}</div>;
  const done = (title, message, action) => <><h1>{title}</h1>{center(<><div className={styles.icon}>✓</div><h2>{title} 완료!</h2><p>{message}</p></>)}{foot(action)}</>;
  let content;
  switch (f.step) {
    case 'welcome': content = <><h1>SIA</h1>{center(<><div className={styles.icon}>S</div><h2>SIA</h2><p>당신의 AI 비서</p>{btn('SIA 시작하기', basic)}</>)}</>; break;
    case 'basic': content = <><h1>기본 설정</h1><div className={styles.fields}><label>비서 이름<input value={name} readOnly aria-readonly="true" /></label>{[['mics', '마이크 선택', mic, setMic], ['cameras', '카메라 선택 (내장 / 외장)', camera, setCamera]].map(([kind, title, value, setter]) => <label key={kind}>{title}<select value={value} onChange={(e) => setter(e.target.value)}><option value="">시스템 기본 장치</option>{devices[kind].map((d) => <option key={d.id} value={d.id}>{d.name}{d.isDefault ? " (기본)" : ""}</option>)}</select></label>)}{btn('장치 목록 새로고침', discover)}{!config && btn('설정 다시 불러오기', basic)}</div>{foot(btn('다음', save, !config))}</>; break;
    case 'micStart': content = <><h1>마이크 설정</h1>{center(<><h2>마이크 설정을 시작합니다</h2><div className={styles.icon}>♩</div></>)}{foot(<>{isMicOnly ? btn('취소', cancelMicEnrollment) : btn('건너뛰기', () => go('gazeStart'))}{btn('시작하기', () => send('wakeword_enroll_start', {}, { step: 'wake', wake: { n: 0, total: 5 }, wakeDone: false, pending: false }), !ready)}</>)}</>; break;
    case 'wake': content = <><h1>이름 불러보기</h1>{center(<><h2>"시아야" 라고 불러주세요</h2><p>샘플 수집 {f.wake.n} / {f.wake.total} · 한 번에 약 {WAKE_SAMPLE_SECONDS}초 안에 또렷하게 불러주세요</p></>)}{foot(btn('다음', () => send('voice_reg_start', {}, { step: 'voice', voiceTempId: null, voiceSentence: null, voiceCompleted: 0, voiceResult: null, finalVoiceReview: null }), !ready || !f.wakeDone))}</>; break;
    case 'voice': {
      const current = f.voiceSentence?.n ?? Math.min(f.voiceCompleted + 1, 5);
      content = <VoiceEnrollment mode="recording" current={current} total={5} sentence={sentences[current - 1] ?? '낭독 문장 원문을 기다리고 있습니다.'} />; break;
    }
    case 'voiceProcessing': content = <VoiceEnrollment mode="processing" />; break;
    case 'voiceReview': {
      const review = f.voiceResult;
      const current = review?.n ?? Math.max(1, f.voiceCompleted);
      const tempId = review?.tempId ?? f.voiceTempId;
      const retry = () => send('voice_sentence_retry', { tempId }, { step: 'voice', voiceResult: null, finalVoiceReview: null, pending: false });
      const accept = () => current >= 5
        ? send('voice_commit', { tempId, ...(selectedDeviceLabel('mic') ? { deviceLabel: selectedDeviceLabel('mic') } : {}) })
        : send('voice_sentence_next', { tempId }, { step: 'voice', voiceSentence: null, voiceResult: null, finalVoiceReview: null });
      content = <VoiceEnrollment mode="review" review={review ?? {}} current={current} total={5} rejected={review?.rejected === true} ready={ready} pending={f.pending} canRetry={Boolean(tempId)} canAccept={current < 5 || Boolean(f.finalVoiceReview)} onRetry={retry} onAccept={accept} />; break;
    }
    case 'micDone': content = done('마이크 설정', '목소리 등록이 완료되었습니다', isMicOnly ? btn('설정으로 돌아가기', () => finishDeviceChange('mic')) : btn('다음 (카메라 설정)', () => go('gazeStart'))); break;
    case 'gazeStart': content = <><h1>시선 설정</h1>{center(<><h2>시선 설정을 시작합니다</h2><div className={styles.icon}>◎</div></>)}{foot(btn('시작하기', () => send('calib_start', {}, { step: 'position', precheck: null, point: null, result: null, poorCount: 0, gazeWaitingSince: Date.now(), gazeDelayed: false, pending: false }), !ready))}</>; break;
    case 'position': content = <><h1>위치 확인</h1>{center(<><p>앉아야 할 자리에 앉아주세요</p><p>화면을 정면으로 바라보고 바른 자세로 앉아주세요</p><p>서버 확인값 — 얼굴: {f.precheck ? (f.precheck.face ? '인식됨' : '미인식') : '확인 중'} · 거리: {f.precheck?.distance ?? '확인 중'} · 조명: {f.precheck?.lighting ?? '확인 중'}</p></>)}{f.gazeDelayed && <p role="status">위치 확인 응답이 지연되고 있습니다. 카메라 설정과 AI 상태를 확인해주세요.</p>}{foot(<>{btn('카메라 설정', cameraSettings, !connected)}{btn('취소', () => send('calib_cancel', {}, { step: 'gazeStart', gazeWaitingSince: null, gazeDelayed: false, pending: false }), !connected)}{btn('다음', () => go('gazeGuide'), !ready || !f.point || !f.precheck?.face || f.precheck.distance !== 'ok' || f.precheck.lighting !== 'ok')}</>)}</>; break;
    case 'gazeGuide': content = center(<><div className={styles.icon}>◎</div><h2>시선 측정을 시작하겠습니다</h2><p>화면에 튀어나오는 두더지의 코를 바라보면 됩니다.<br />약 1분 정도 걸립니다.</p><div className={styles.preview}>· 화면과 60~80cm 거리를 유지해주세요<br />· 보정 중에는 고개를 크게 움직이지 마세요<br />· 안경을 쓴다면 평소 사용하는 상태로 진행해주세요</div><div className={styles.actions}>{btn('취소', () => send('calib_cancel', {}, { step: 'gazeStart', pending: false }), !ready)}{btn('시작하기', () => measure(), !ready)}</div></>); break;
    case 'measuring': content = <GazeMeasurement point={f.point} ready={ready} connected={connected} onCancel={() => send('calib_cancel', {}, { step: 'gazeStart', pending: false })} />; break;
    case 'result': {
      const r = f.result; const poor = r.grade === 'poor'; const exhausted = f.poorCount >= 3 || r.remeasuresLeft === 0;
      const extent = Math.max(100, ...(r.points ?? []).flatMap((p) => [Math.abs(p.dx), Math.abs(p.dy)])) * 1.2;
      content = <><h1>시선 학습 결과</h1>{center(<><div className={styles.plot}><svg viewBox={`${-extent} ${-extent} ${extent * 2} ${extent * 2}`} aria-label="목표점 기준 시선 오차 분포"><circle cx="0" cy="0" r={extent / 40} className={styles.target} />{r.points?.map((p) => <circle key={p.n} cx={p.dx} cy={p.dy} r={extent / 30} />)}</svg><p>점: 목표 지점 · 원: 실제 측정된 시선 위치 (오차)</p></div><h2>오차 범위 : {{ excellent: '우수', good: '양호', poor: '나쁨' }[r.grade] ?? '미제공'}</h2>{poor && <p>{exhausted ? '지속적으로 큰 오차가 발생하고 있습니다. 카메라 설정을 확인한 후 다시 측정해주십시오.' : '오차가 다소 큽니다. 시선을 다시 측정해주세요.'}</p>}<p>남은 재측정: {r.remeasuresLeft}회</p></>)}{foot(<>{exhausted && poor ? btn('카메라 설정', cameraSettings, !connected) : btn('다시 측정', () => measure(true), !ready || !r.remeasuresLeft)}{!poor && btn('계속 진행', () => send('calib_commit', selectedDeviceLabel('camera') ? { deviceLabel: selectedDeviceLabel('camera') } : {}), !ready || r.pass !== true)}</>)}</>; break;
    }
    case 'gazeDone': content = done('시선 설정', '시선 학습이 완료되었습니다', isCameraOnly ? btn('설정으로 돌아가기', () => finishDeviceChange('camera')) : btn('다음', () => go('done'))); break;
    default: content = done('설정', '이제 SIA를 시작할 수 있습니다.', <Link className={styles.linkButton} to="/dashboard">완료</Link>);
  }
  const cardClassName = ['voice', 'voiceProcessing', 'voiceReview'].includes(f.step) ? `${styles.card} ${styles.wideCard}` : styles.card;
  return <main className={styles.page}><section className={cardClassName} aria-label="첫 설정">{content}{f.pending && <p role="status">서버 응답을 기다리고 있습니다.</p>}{f.request?.delayed && <p role="status">{f.request.type} 응답이 30초 이상 지연되고 있습니다. 연결 상태를 확인해주세요. 응답이 도착하면 계속 진행합니다.</p>}{f.connectionError && <p className={styles.error} role="alert">{f.connectionError}</p>}{f.error && <p className={styles.error} role="alert">{f.error}</p>}{f.interrupted && btn('처음부터 다시 설정', () => { change({ interrupted: false }); go('welcome'); }, !connected)}</section><p className={styles.connection}>실시간 연결: {connected ? '연결됨' : '대기 중'} · AI: {f.status?.agentConnected ? '연결됨' : '대기 중'}</p></main>;
}
