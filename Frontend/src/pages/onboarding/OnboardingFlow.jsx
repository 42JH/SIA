import { useEffect, useRef, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { fetchSettings, updateSettings } from '../../api/settings';
import { fetchDevices } from '../../api/devices';
import { registerInstalledApps } from '../../api/onboarding';
import { sendOnboarding } from '../../ws/onboarding';
import { startGesturePreview, stopGesturePreview, subscribeGestures } from '../../ws/gestures';
import { useSessionStore } from '../../store/sessionStore';
import { useOnboardingStore } from '../../store/onboardingStore';
import { useOnboarding } from './useOnboarding';
import OnboardingWakeView from './OnboardingWakeView';
import GazeMeasurement from '../../components/onboarding/GazeMeasurement';
import VoiceEnrollment from '../../components/onboarding/VoiceEnrollment';
import MicLevelWaveform from '../../components/onboarding/MicLevelWaveform';
import { useMicPreview } from '../../hooks/useMicPreview';
import logo from '../../assets/sia-logo.png';
import styles from './OnboardingHome.module.css';

import { ENROLLMENT_SENTENCES as sentences } from './enrollmentConstants';

const DEFAULT_WAKE_WORD = '시아야';
const VOICE_INCOMPLETE_STEPS = ['basic', 'micStart', 'wake', 'voice', 'voiceProcessing', 'voiceReview'];

function normalizeWakeWord(value) {
  const next = typeof value === 'string' ? value.trim() : '';
  return next || DEFAULT_WAKE_WORD;
}

function wakeWordIssue(value) {
  const next = typeof value === 'string' ? value.trim() : '';
  if (!next) return '한국어 이름으로 입력해주세요.';
  if (!/^[가-힣]+$/.test(next)) {
    return '호출명(wakeWord) 설정은 완성된 한글로만 이루어져야 합니다 (예: "시아야"). 자모 · 영문 · 숫자 · 기호 · 공백은 쓸 수 없습니다';
  }
  if (next.length < 2 || next.length > 8) {
    return `호출명(wakeWord) 설정은 2~8글자여야 합니다 (지금 ${next.length}글자)`;
  }
  return '';
}

function readPendingWakeWord() {
  try { return (sessionStorage.getItem('siaPendingWakeWord') || '').trim(); }
  catch { return ''; }
}
function clearPendingWakeWord() {
  try { sessionStorage.removeItem('siaPendingWakeWord'); } catch { /* ignore */ }
}
function quotedWakeWord(reason, expected) {
  if (!reason || !expected) return reason;
  return reason.replace(/[“”"']([^“”"']+)[“”"']/g, `“${expected}”`);
}
function breakSentences(text) {
  return String(text ?? '').replace(/([.!?])\s+/g, '$1\n').trim();
}
function isOnboardingRoute() {
  return window.location.pathname.includes('/onboarding');
}

const GRADE_EXCELLENT_PX = 160;
const GRADE_GOOD_PX = 250;

function precheckLabel(value, okWhen) {
  if (value == null || value === '-') return '확인 중';
  if (okWhen(value)) return '✓';
  if (typeof value === 'string' && value !== 'ok') return value;
  return '확인 필요';
}

function WelcomeOrb() {
  return (
    <div className={styles.welcomeOrb} aria-hidden="true">
      <svg className={styles.welcomeOrbImage} viewBox="0 0 240 240">
        <g fill="none" stroke="#7aa0cc" strokeWidth="1.35">
          <ellipse cx="120" cy="120" rx="102" ry="38" transform="rotate(-20 120 120)" />
          <ellipse cx="120" cy="120" rx="100" ry="37" transform="rotate(50 120 120)" />
          <ellipse cx="120" cy="120" rx="98" ry="36" transform="rotate(110 120 120)" />
        </g>
        <g fill="#163a6e">
          <circle cx="216.7" cy="90.4" r="5.2" />
          <circle cx="199.9" cy="118" r="3.1" />
          <circle cx="45.6" cy="168.5" r="4.4" />
          <circle cx="24.8" cy="142.1" r="5" />
          <circle cx="182.5" cy="70.2" r="3.4" />
          <circle cx="172.4" cy="200.2" r="4.6" />
          <circle cx="61.9" cy="99.6" r="5.1" />
          <circle cx="98.1" cy="51.1" r="3.6" />
          <circle cx="79.9" cy="127.1" r="5" />
          <circle cx="157.9" cy="30.5" r="4.2" />
          <circle cx="106.3" cy="207.1" r="3.8" />
          <circle cx="75.6" cy="199.1" r="3.2" />
        </g>
        <g fill="#8aa8cc">
          <circle cx="136.3" cy="154.5" r="2.2" />
          <circle cx="78" cy="96.8" r="1.6" />
          <circle cx="115.4" cy="168.5" r="2.4" />
          <circle cx="53.5" cy="45.8" r="1.8" />
          <circle cx="176.7" cy="137.7" r="2" />
          <circle cx="123.9" cy="41.5" r="2.1" />
          <circle cx="163.3" cy="100.1" r="1.5" />
          <circle cx="148" cy="88" r="1.4" />
          <circle cx="92" cy="78" r="1.3" />
        </g>
      </svg>
    </div>
  );
}

function MicGraphic() {
  return <div className={styles.sideMark} aria-hidden="true">
    <i className={styles.micRipple} />
    <i className={styles.micRipple} />
    <i className={styles.micRipple} />
    <span className={styles.micCircle}>
      <svg viewBox="70 64 80 120">
        <path d="M110 76c-9 0-16 7-16 16v30c0 9 7 16 16 16s16-7 16-16V92c0-9-7-16-16-16zm-28 46c0 16 12 30 28 30s28-14 28-30M110 152v18M96 170h28" />
      </svg>
    </span>
  </div>;
}

function CheckGraphic() {
  return <div className={styles.checkGraphic} aria-hidden="true"><span>✓</span></div>;
}

function GazeResultPlot({ result }) {
  const points = result.points ?? [];
  const maxError = Math.max(40, ...points.flatMap((point) => [Math.abs(Number(point.dx) || 0), Math.abs(Number(point.dy) || 0)]));
  const scale = 38 / maxError;
  return <div className={styles.plot}><svg viewBox="-170 -130 340 260" preserveAspectRatio="xMidYMid meet" aria-label="목표점과 실제 시선 위치">
    <circle className={styles.guideCircle} cx="0" cy="0" r="58" />
    {points.map((point) => {
      const column = (point.n - 1) % 3 - 1;
      const row = Math.floor((point.n - 1) / 3) - 1;
      const targetX = column * 46;
      const targetY = row * 34;
      const measuredX = targetX + Number(point.dx) * scale;
      const measuredY = targetY + Number(point.dy) * scale;
      return <g key={point.n}><circle className={styles.targetPoint} cx={targetX} cy={targetY} r="7" /><line x1={targetX} y1={targetY} x2={measuredX} y2={measuredY} /><circle className={styles.measuredPoint} cx={measuredX} cy={measuredY} r="5" /></g>;
    })}
    <circle className={styles.plotCenter} cx="0" cy="0" r="8" />
  </svg></div>;
}

function FrameChrome() {
  return (
    <>
      <svg className={styles.frameChrome} viewBox="0 0 1000 600" preserveAspectRatio="none" aria-hidden="true">
        <path className={styles.frameSurface} d="M28 8H962L992 38V562L962 592H38L8 562V38Z" />
      </svg>
      <span className={styles.frameAccent} aria-hidden="true" />
    </>
  );
}

function FrameTitle({ children }) {
  return <h1 className={styles.frameTitle}>{children}</h1>;
}

function CameraPositionPreview({ precheck }) {
  const previewSeq = useRef(-1);
  const previewImg = useRef(null);
  const [hasFrame, setHasFrame] = useState(false);
  const [ready, setReady] = useState(false);
  const [cameraError, setCameraError] = useState('');
  const connected = useSessionStore((state) => state.wsConnected);

  useEffect(() => {
    if (!connected) return undefined;
    let cancelled = false;
    let retryTimer;
    const requestStart = () => {
      if (cancelled) return;
      try {
        startGesturePreview();
      } catch (error) {
        setReady(false);
        setCameraError(error.message);
        retryTimer = setTimeout(requestStart, 1200);
      }
    };
    const unsubscribe = subscribeGestures({
      cam_preview_state: (data) => {
        if (cancelled) return;
        if (data.phase === 'READY') {
          setReady(true);
          setCameraError('');
        } else if (data.phase === 'ERROR') {
          setReady(false);
          setCameraError(data.message || 'AI 카메라 화면을 불러올 수 없습니다.');
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
        setReady(true);
        setCameraError('');
        setHasFrame(true);
      },
      error: (data) => {
        if (cancelled || data.of !== 'cam_preview_start') return;
        setReady(false);
        setCameraError(data.message || 'AI 카메라 화면을 불러올 수 없습니다.');
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
    };
  }, [connected]);

  return <div className={styles.cameraPreview}>
    <img ref={previewImg} className={styles.cameraVideo} alt="AI 카메라 미리보기" hidden={!hasFrame} />
    {!hasFrame && <span className={styles.cameraWaiting}>{ready ? '카메라 화면을 기다리고 있습니다.' : 'AI 카메라를 준비하고 있습니다.'}</span>}
    <div className={styles.cameraShade} />
    <span className={styles.cameraLive}>● CAMERA LIVE</span>
    <p>화면 중앙에 바른 자세로 앉아주세요.</p>
    <small>얼굴 {precheckLabel(precheck?.face, (value) => value === true)} · 거리 {precheckLabel(precheck?.distance, (value) => value === 'ok')} · 조명 {precheckLabel(precheck?.lighting, (value) => value === 'ok')}</small>
    {cameraError && <em className={styles.cameraError} role="alert">{cameraError}</em>}
  </div>;
}

export default function OnboardingFlow() {
  useOnboarding();
  const location = useLocation();
  const navigate = useNavigate();
  const f = useOnboardingStore();
  const connected = useSessionStore((s) => s.wsConnected);
  const [config, setConfig] = useState(null);
  const [devices, setDevices] = useState({ mics: [], cameras: [] });
  const [name, setName] = useState(() => {
    const fromState = typeof location.state?.wakeWord === 'string' ? location.state.wakeWord.trim() : '';
    const fromQuery = (new URLSearchParams(location.search).get('wakeWord') || '').trim();
    return fromState || fromQuery || readPendingWakeWord() || DEFAULT_WAKE_WORD;
  });
  const [mic, setMic] = useState('');
  const [camera, setCamera] = useState('');
  const [cameraSettingsOnly, setCameraSettingsOnly] = useState(false);
  const voiceCommittedRef = useRef(false);
  const loadedWakeRef = useRef(DEFAULT_WAKE_WORD);
  const savedWakeThisSessionRef = useRef(false);
  const flowMode = new URLSearchParams(location.search).get('mode');
  const previousWakeWord = typeof location.state?.previousWakeWord === 'string' ? location.state.previousWakeWord.trim() : '';
  const incomingWakeWord = (typeof location.state?.wakeWord === 'string' ? location.state.wakeWord.trim() : '')
    || (new URLSearchParams(location.search).get('wakeWord') || '').trim()
    || readPendingWakeWord();
  const isWakeOnly = flowMode === 'wake';
  const isMicOnly = flowMode === 'mic';
  const isCameraOnly = flowMode === 'camera';
  const enrollWakeWord = (isWakeOnly ? (incomingWakeWord || readPendingWakeWord()) : name).trim();
  const fromSettings = isWakeOnly || isMicOnly;
  const deviceChange = location.state?.deviceChange;
  const [wakeWordReady, setWakeWordReady] = useState(!incomingWakeWord);

  const ready = connected && f.status?.agentConnected && !f.interrupted && wakeWordReady;
  const micPreviewActive = (f.step === 'wake' ? !f.wakeDone : ['voice', 'voiceProcessing', 'voiceReview'].includes(f.step));
  const voiceWaveN = f.voiceSentence?.n ?? (f.step === 'voice' ? Math.min((f.voiceCompleted || 0) + 1, 5) : (f.voiceResult?.n ?? f.voiceCompleted));
  const wakeRejectionMessage = /호출어가|새 이름/.test(f.wakeRejection?.reason ?? '')
    ? `호출어가 “${enrollWakeWord}”(으)로 바뀌었어요. 새 이름으로 다시 5번 불러주세요.`
    : quotedWakeWord(f.wakeRejection?.reason, enrollWakeWord);
  const micPreview = useMicPreview(micPreviewActive && connected, `${f.step}-${f.wake.n}-${voiceWaveN}`);
  const change = f.change;
  useEffect(() => {
    let cancelled = false;
    if (previousWakeWord) {
      loadedWakeRef.current = previousWakeWord;
      savedWakeThisSessionRef.current = true;
    }
    if (incomingWakeWord) setName(incomingWakeWord);
    fetchSettings().then((data) => {
      if (cancelled) return;
      const current = normalizeWakeWord(data.settings.wakeWord);
      if (!previousWakeWord) loadedWakeRef.current = current;
    }).catch(() => {}).finally(() => {
      if (!cancelled) setWakeWordReady(true);
    });
    return () => { cancelled = true; };
  }, [previousWakeWord, incomingWakeWord, isWakeOnly]);
  useEffect(() => {
    if (f.step !== 'voiceReview') return;
    if (!micPreview.envelope.some((level) => level > 0.08)) return;
    if ((f.voiceWaveform ?? []).some((level) => level > 0.08)) return;
    change({ voiceWaveform: micPreview.envelope });
  }, [f.step, micPreview.envelope, f.voiceWaveform, change]);
  useEffect(() => {
    if (f.step === 'micDone') voiceCommittedRef.current = true;
  }, [f.step]);
  useEffect(() => {
    if (!isWakeOnly || f.step !== 'wake' || !f.wakeDone) return undefined;
    voiceCommittedRef.current = true;
    fetchSettings().then((data) => {
      setName(normalizeWakeWord(data.settings.wakeWord));
    }).catch(() => {}).finally(() => {
      clearPendingWakeWord();
      change({ step: 'micDone', pending: false, request: null });
    });
    return undefined;
  }, [isWakeOnly, f.step, f.wakeDone, change]);
  async function restorePreviousWakeWord() {
    return;
  }
  useEffect(() => () => {
    if (isOnboardingRoute()) return;
    const state = useOnboardingStore.getState();
    if (state.step === 'wake') {
      try { sendOnboarding('wakeword_enroll_cancel', {}); } catch { /* 이탈 시 화면 상태 초기화 우선 */ }
    }
    if (state.voiceTempId && ['voice', 'voiceProcessing', 'voiceReview'].includes(state.step)) {
      try { sendOnboarding('voice_reg_cancel', { tempId: state.voiceTempId }); } catch { /* 이탈 시 화면 상태 초기화 우선 */ }
    }
    if (isMicOnly || isWakeOnly) state.resetVoiceEnrollment();
    if (VOICE_INCOMPLETE_STEPS.includes(state.step)) restorePreviousWakeWord();
  }, [isMicOnly, isWakeOnly, isCameraOnly, previousWakeWord]);
  useEffect(() => {
    const requestedStep = new URLSearchParams(window.location.search).get('step');
    if (requestedStep === 'micStart' || requestedStep === 'gazeStart') {
      if (requestedStep === 'micStart') useOnboardingStore.getState().resetVoiceEnrollment();
      else change({
        step: requestedStep, pending: false, error: '', interrupted: false, request: null,
        precheck: null, point: null, result: null, poorCount: 0,
        gazeWaitingSince: null, gazeDelayed: false,
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
  function finishWakeChange() {
    clearPendingWakeWord();
    change({ step: 'welcome', pending: false, interrupted: false });
    navigate('/dashboard?view=settings');
  }
  async function cancelMicEnrollment() {
    if (f.step === 'wake' && connected) {
      try { sendOnboarding('wakeword_enroll_cancel', {}); } catch (error) { change({ error: error.message }); }
    }
    if (f.voiceTempId && connected) {
      try { sendOnboarding('voice_reg_cancel', { tempId: f.voiceTempId }); } catch (error) { change({ error: error.message }); }
    }
    await restorePreviousWakeWord();
    if (!isMicOnly) setName(loadedWakeRef.current);
    clearPendingWakeWord();
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
  function startWakeEnrollment() {
    const word = enrollWakeWord.trim();
    const issue = wakeWordIssue(word);
    if (issue) {
      change({ error: issue, pending: false });
      return;
    }
    send('wakeword_enroll_start', { wakeWord: word }, { step: 'wake', wake: { n: 0, total: 5 }, wakeDone: false, wakeRejection: null, pending: false });
  }
  async function basic() {
    go('basic');
    await run(async () => {
      const [settingsResult, devicesResult] = await Promise.allSettled([fetchSettings(), fetchDevices()]);
      if (devicesResult.status === 'fulfilled') setDevices(devicesResult.value);
      if (settingsResult.status === 'fulfilled') {
        const data = settingsResult.value;
        setConfig(data);
        loadedWakeRef.current = normalizeWakeWord(data.settings.wakeWord);
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
  async function save() {
    await run(async () => {
      try {
        const nextName = name.trim();
        setConfig(await updateSettings({ settings: { ...config.settings, micDevice: label(mic, 'mics'), micDeviceId: mic || null, cameraDevice: label(camera, 'cameras'), cameraDeviceId: camera || null }, updatedAt: config.updatedAt }));
        savedWakeThisSessionRef.current = nextName !== loadedWakeRef.current;
      }
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
  const btn = (text, action, disabled = false, tone = 'primary') => <button className={styles[tone]} onClick={action} disabled={disabled || f.pending}>{text}</button>;
  const foot = (children) => <footer className={styles.footer}>{children}</footer>;
  const center = (children, className = '') => <div className={`${styles.center} ${className}`}>{children}</div>;
  const done = (title, heading, message, action) => <><FrameTitle>{title}</FrameTitle>{center(<><CheckGraphic /><h2>{heading}</h2><p>{message}</p></>, styles.doneCenter)}{foot(action)}</>;
  if (isWakeOnly) {
    return <OnboardingWakeView
      step={f.step}
      wakeDone={f.wakeDone}
      wake={f.wake}
      enrollWakeWord={enrollWakeWord}
      rejection={f.wakeRejection ? breakSentences(wakeRejectionMessage) : ''}
      micLevels={micPreview.levels}
      micError={micPreview.error}
      canStart={ready && !wakeWordIssue(enrollWakeWord)}
      pending={f.pending}
      error={f.error}
      connectionError={f.connectionError}
      delayed={f.request?.delayed}
      onStart={startWakeEnrollment}
      onCancel={cancelMicEnrollment}
      onFinish={finishWakeChange}
    />;
  }
  let content;
  switch (f.step) {
    case 'welcome': content = <><div className={styles.welcomeContent}><div className={styles.welcomeCopy}><h1>어서오세요!</h1><span className={styles.titleRule} /><h2>SIA</h2><p>당신의 AI 비서</p></div><WelcomeOrb /></div>{foot(btn('SIA 시작하기', basic))}</>; break;
    case 'basic': content = <><FrameTitle>기본 설정</FrameTitle><div className={styles.fields}><label>호출명 (Wake Word)<input value={name} onChange={(e) => setName(e.target.value)} /><small>{wakeWordIssue(name) || '한국어 이름으로 입력해주세요.'}</small></label><label>마이크 선택(내장 / 외장)<select value={mic} onChange={(e) => setMic(e.target.value)}><option value="">마이크를 선택해주세요</option>{devices.mics.map((d) => <option key={d.id} value={d.id}>{d.name}{d.isDefault ? ' (기본)' : ''}</option>)}</select></label><label>카메라 선택(내장 / 외장)<select value={camera} onChange={(e) => setCamera(e.target.value)}><option value="">카메라를 선택해주세요</option>{devices.cameras.map((d) => <option key={d.id} value={d.id}>{d.name}{d.isDefault ? ' (기본)' : ''}</option>)}</select></label>{!config && btn('설정 다시 불러오기', basic, false, 'secondary')}</div>{foot(btn('다음', save, !config || Boolean(wakeWordIssue(name))))}</>; break;
    case 'micStart': content = <><FrameTitle>{isWakeOnly ? '호출명 변경' : '마이크 설정'}</FrameTitle>{center(<><p className={styles.lead}>{isWakeOnly ? '호출명을 등록합니다' : '마이크 설정을 시작합니다'}</p><p className={styles.startHint}>마이크 등록은 주변 소음이 적은 조용한 환경에서 진행하는 것을 권장합니다.</p><MicGraphic /></>, styles.startCenter)}{foot(<>{fromSettings && btn('취소', cancelMicEnrollment, false, 'secondary')}{btn('시작하기', startWakeEnrollment, !ready || Boolean(wakeWordIssue(enrollWakeWord)))}</>)}</>; break;
    case 'wake': content = <><FrameTitle>이름 불러보기</FrameTitle>{center(<>{f.wakeDone ? <><h2>호출명 학습이 완료되었습니다</h2>{!isWakeOnly && <p>화자등록으로 넘어가 주세요.</p>}</> : <><h2>“{enrollWakeWord}”라고 불러주세요</h2><p>샘플 수집 {f.wake.n} / {f.wake.total} · 호출어만 짧고 또렷하게 불러주세요</p></>}{!f.wakeDone && <MicLevelWaveform levels={micPreview.levels} />}{f.wakeRejection && <p className={styles.rejection} role="status">{breakSentences(wakeRejectionMessage)}</p>}{!f.wakeDone && micPreview.error && <p className={styles.error} role="status">{micPreview.error}</p>}</>, styles.wakeCenter)}{foot(<>{fromSettings && btn('취소', cancelMicEnrollment, false, 'secondary')}{!isWakeOnly && btn('다음', () => send('voice_reg_start', {}, { step: 'voice', voiceTempId: null, voiceSentence: null, voiceCompleted: 0, voiceResult: null, finalVoiceReview: null }), !ready || !f.wakeDone)}</>)}</>; break;
    case 'voice': {
      const current = f.voiceSentence?.n ?? Math.min(f.voiceCompleted + 1, 5);
      content = <VoiceEnrollment mode="recording" current={current} total={5} sentence={sentences[current - 1] ?? '낭독 문장 원문을 기다리고 있습니다.'} micLevels={micPreview.levels} />; break;
    }
    case 'voiceProcessing': content = <VoiceEnrollment mode="processing" />; break;
    case 'voiceReview': {
      const review = f.voiceResult;
      const current = review?.n ?? Math.max(1, f.voiceCompleted);
      const tempId = review?.tempId ?? f.voiceTempId;
      const retry = () => send('voice_sentence_retry', { tempId }, { step: 'voice', voiceResult: null, finalVoiceReview: null, voiceWaveform: [], pending: false });
      const accept = () => current >= 5
        ? send('voice_commit', { tempId, ...(selectedDeviceLabel('mic') ? { deviceLabel: selectedDeviceLabel('mic') } : {}) })
        : send('voice_sentence_next', { tempId }, { step: 'voice', voiceSentence: null, voiceResult: null, finalVoiceReview: null, voiceWaveform: [] });
      content = <VoiceEnrollment mode="review" review={review ?? {}} waveform={(f.voiceWaveform ?? []).some((level) => level > 0.08) ? f.voiceWaveform : micPreview.envelope} current={current} total={5} rejected={review?.rejected === true} ready={ready} pending={f.pending} canRetry={Boolean(tempId)} canAccept={current < 5 || Boolean(f.finalVoiceReview)} onRetry={retry} onAccept={accept} />; break;
    }
    case 'micDone': content = isWakeOnly
      ? done('호출명 변경', '등록완료', '호출명이 변경되었습니다.', btn('설정으로 돌아가기', finishWakeChange))
      : done('마이크 설정', '마이크 설정 완료!', '목소리 등록이 완료되었습니다.', isMicOnly ? btn('설정으로 돌아가기', () => finishDeviceChange('mic')) : btn('다음 (카메라 설정)', () => go('gazeStart'))); break;
    case 'gazeStart': content = <><FrameTitle>시선 설정</FrameTitle>{center(<><p className={styles.lead}>시선 설정을 시작합니다</p><div className={styles.gazeStartGraphic} aria-hidden="true"><span className={styles.scopeOuter} /><span className={styles.scopeMiddle} /><span className={styles.scopeInner} /><i className={styles.scopeCross} /><b className={styles.scopeDot} /></div></>, styles.startCenter)}{foot(btn('시작하기', () => send('calib_start', {}, { step: 'position', precheck: null, point: null, result: null, poorCount: 0, gazeWaitingSince: Date.now(), gazeDelayed: false, pending: false }), !ready))}</>; break;
    case 'position': {
      const validPosition = Boolean(f.precheck?.face && f.precheck.distance === 'ok' && f.precheck.lighting === 'ok');
      content = <><FrameTitle>위치 확인</FrameTitle>{center(<CameraPositionPreview precheck={f.precheck} />, styles.positionCenter)}{f.gazeDelayed && <p className={styles.inlineNotice} role="status">위치 확인 응답이 지연되고 있습니다. 카메라 설정과 AI 상태를 확인해주세요.</p>}{foot(<>{btn('카메라 설정', cameraSettings, !connected, 'secondary')}{btn('다음', () => go('gazeGuide'), !ready || !validPosition)}</>)}</>; break;
    }
    case 'gazeGuide': content = <><FrameTitle>시선 측정</FrameTitle>{center(<><div className={styles.guideGraphic}>◎</div><h2>시선 측정을 시작하겠습니다</h2><p>화면 중앙에 바른 자세로 앉아주세요.<br />너무 멀거나 가깝지 않게, 조명이 너무 어둡거나 밝지 않은 곳에서 고개를 크게 움직이지 마세요.</p></>, styles.guideCenter)}{foot(<>{isCameraOnly && btn('취소', () => send('calib_cancel', {}, { step: 'gazeStart', pending: false }), !ready, 'secondary')}{btn('시작하기', () => measure(), !ready)}</>)}</>; break;
    case 'measuring': content = <GazeMeasurement point={f.point} ready={ready} />; break;
    case 'result': {
      const r = f.result;
      const displayGrade = r.avgErrorPx == null ? '미제공' : (({ excellent: '우수', good: '양호', poor: '나쁨' }[r.grade]) ?? (r.avgErrorPx < GRADE_EXCELLENT_PX ? '우수' : r.avgErrorPx < GRADE_GOOD_PX ? '양호' : '나쁨'));
      const poor = r.pass !== true || displayGrade === '나쁨' || displayGrade === '인식 불가';
      const exhausted = poor && (f.poorCount >= 3 || r.remeasuresLeft === 0);
      const errors = (r.points ?? []).map((point) => Math.hypot(Number(point.dx), Number(point.dy))).filter(Number.isFinite);
      const average = r.avgErrorPx == null ? '미제공' : `${Math.round(r.avgErrorPx)}px`;
      const maximum = r.maxErrorPx == null ? '미제공' : `${Math.round(r.maxErrorPx)}px`;
      const minimum = r.minErrorPx == null ? (errors.length ? `${Math.round(Math.min(...errors))}px` : '미제공') : `${Math.round(r.minErrorPx)}px`;
      content = <><FrameTitle>시선 측정 결과</FrameTitle>{center(<div className={styles.resultBoard}><GazeResultPlot result={r} /><div className={styles.resultCopy}><small>○ 목표 지점 · ● 실제 측정된 시선</small><h2>최소 {minimum} · 평균 {average} · 최대 {maximum}</h2><strong className={poor ? styles.badGrade : ''}>오차 범위 : {displayGrade}</strong>{poor && <p>{exhausted ? '지속적으로 큰 오차가 발생했습니다. 카메라 설정을 다시 확인해주세요.' : '오차가 다소 큽니다. 시선을 다시 측정해주세요.'}</p>}</div></div>, styles.resultCenter)}{foot(<>{exhausted && poor ? btn('카메라 설정', cameraSettings, !connected) : btn('다시 측정', () => measure(true), !ready || !r.remeasuresLeft, 'secondary')}{!poor && btn('계속 진행', () => send('calib_commit', selectedDeviceLabel('camera') ? { deviceLabel: selectedDeviceLabel('camera') } : {}), !ready || r.pass !== true)}</>)}</>; break;
    }
    case 'gazeDone': content = done('시선 설정', '시선 설정 완료!', '시선 학습이 완료되었습니다.', isCameraOnly ? btn('설정으로 돌아가기', () => finishDeviceChange('camera')) : btn('다음', () => go('done'))); break;
    default: content = done('설정 완료', '완료!', '이제 SIA를 시작할 수 있습니다.', <Link className={styles.linkButton} to="/dashboard">완료</Link>);
  }
  const stepClassName = styles[`step_${f.step}`] ?? '';
  return <main className={styles.page}><section className={`${styles.card} ${stepClassName}`} aria-label="첫 설정"><FrameChrome /><img className={styles.logo} src={logo} alt="SIA" />{content}<div className={styles.systemMessages}>{f.pending && <p role="status">서버 응답을 기다리고 있습니다.</p>}{f.request?.delayed && <p role="status">{f.request.type} 응답이 30초 이상 지연되고 있습니다. 연결 상태를 확인해주세요.</p>}{f.connectionError && <p className={styles.error} role="alert">{f.connectionError}</p>}{f.error && <p className={styles.error} role="alert">{f.error}</p>}{f.interrupted && btn('처음부터 다시 설정', () => { restorePreviousWakeWord(); setName(loadedWakeRef.current); change({ interrupted: false }); go('welcome'); }, !connected, 'secondary')}</div></section><p className={styles.connection}>실시간 연결: {connected ? '연결됨' : '대기 중'} · AI: {f.status?.agentConnected ? '연결됨' : '대기 중'}</p></main>;
}
