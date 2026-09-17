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
import MicLevelWaveform from '../../components/onboarding/MicLevelWaveform';
import { useMicPreview } from '../../hooks/useMicPreview';
import logo from '../../assets/sia-logo.png';
import onboardingOrb from '../../assets/onboarding-orb.png';
import styles from './OnboardingHome.module.css';

import { ENROLLMENT_SENTENCES as sentences } from './enrollmentConstants';

function MicGraphic() {
  return <div className={styles.micGraphic} aria-hidden="true"><span /><i /><b /></div>;
}

function CheckGraphic() {
  return <div className={styles.checkGraphic} aria-hidden="true"><span>✓</span></div>;
}

function WelcomeOrb() {
  const [active, setActive] = useState(false);
  const move = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    event.currentTarget.style.setProperty('--orb-x', `${((event.clientX - rect.left) / rect.width - .5) * 14}deg`);
    event.currentTarget.style.setProperty('--orb-y', `${((event.clientY - rect.top) / rect.height - .5) * -14}deg`);
  };
  const reset = (event) => { event.currentTarget.style.setProperty('--orb-x', '0deg'); event.currentTarget.style.setProperty('--orb-y', '0deg'); };
  return <button type="button" className={`${styles.welcomeOrb} ${active ? styles.orbActive : ''}`} onPointerMove={move} onPointerLeave={reset} onClick={() => setActive((value) => !value)} aria-label="SIA 구체 움직이기"><span className={styles.orbTilt}><img src={onboardingOrb} alt="" /><svg className={styles.orbitLayer} viewBox="0 0 380 280" aria-hidden="true"><g className={styles.orbitOne}><ellipse cx="190" cy="140" rx="150" ry="48" /><circle cx="40" cy="140" r="5" /><circle cx="315" cy="113" r="4" /></g><g className={styles.orbitTwo}><ellipse cx="190" cy="140" rx="142" ry="55" /><circle cx="69" cy="111" r="5" /><circle cx="324" cy="157" r="4" /></g><g className={styles.orbitThree}><ellipse cx="190" cy="140" rx="137" ry="44" /><circle cx="57" cy="151" r="4" /><circle cx="302" cy="115" r="5" /></g></svg></span></button>;
}

function FrameChrome() {
  return (
    <svg className={styles.frameChrome} viewBox="0 0 920 550" preserveAspectRatio="none" aria-hidden="true">
      <path className={styles.frameSurface} d="M25 2H895L918 25V525L895 548H25L2 525V25L25 2Z" />
      <path className={styles.frameGuide} d="M70 516H250" />
    </svg>
  );
}

function FrameTitle({ children }) {
  return <h1 className={styles.frameTitle}>{children}</h1>;
}

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
  const micPreviewActive = ['wake', 'voice', 'voiceProcessing', 'voiceReview'].includes(f.step);
  const micPreview = useMicPreview(micPreviewActive && connected);
  const change = f.change;
  useEffect(() => () => {
    if (!isMicOnly) return;
    const state = useOnboardingStore.getState();
    if (state.voiceTempId && ['voice', 'voiceProcessing', 'voiceReview'].includes(state.step)) {
      try { sendOnboarding('voice_reg_cancel', { tempId: state.voiceTempId }); } catch { /* 이탈 시 화면 상태 초기화 우선 */ }
    }
    state.resetVoiceEnrollment();
  }, [isMicOnly]);
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
  const btn = (text, action, disabled = false, tone = 'primary') => <button className={styles[tone]} onClick={action} disabled={disabled || f.pending}>{text}</button>;
  const foot = (children) => <footer className={styles.footer}>{children}</footer>;
  const center = (children, className = '') => <div className={`${styles.center} ${className}`}>{children}</div>;
  const done = (title, heading, message, action) => <><FrameTitle>{title}</FrameTitle>{center(<><CheckGraphic /><h2>{heading}</h2><p>{message}</p></>, styles.doneCenter)}{foot(action)}</>;
  let content;
  switch (f.step) {
    case 'welcome': content = <div className={styles.welcomeContent}><div className={styles.welcomeCopy}><h1>어서오세요!</h1><span className={styles.titleRule} /><h2>SIA</h2><p>당신의 AI 비서</p>{btn('SIA 시작하기', basic)}</div><WelcomeOrb /></div>; break;
    case 'basic': content = <><FrameTitle>기본 설정</FrameTitle><div className={styles.fields}><label>마이크 선택(내장 / 외장)<select value={mic} onChange={(e) => setMic(e.target.value)}><option value="">마이크를 선택해주세요</option>{devices.mics.map((d) => <option key={d.id} value={d.id}>{d.name}{d.isDefault ? ' (기본)' : ''}</option>)}</select></label><label>카메라 선택(내장 / 외장)<select value={camera} onChange={(e) => setCamera(e.target.value)}><option value="">카메라를 선택해주세요</option>{devices.cameras.map((d) => <option key={d.id} value={d.id}>{d.name}{d.isDefault ? ' (기본)' : ''}</option>)}</select></label>{!config && btn('설정 다시 불러오기', basic, false, 'secondary')}</div>{foot(btn('다음', save, !config))}</>; break;
    case 'micStart': content = <><FrameTitle>마이크 설정</FrameTitle>{center(<><p className={styles.lead}>마이크 설정을 시작합니다</p><MicGraphic /></>, styles.startCenter)}{foot(<>{isMicOnly && btn('취소', cancelMicEnrollment, false, 'secondary')}{btn('시작하기', () => send('wakeword_enroll_start', {}, { step: 'wake', wake: { n: 0, total: 5 }, wakeDone: false, wakeRejection: null, pending: false }), !ready)}</>)}</>; break;
    case 'wake': content = <><FrameTitle>이름 불러보기</FrameTitle>{center(<><h2>“시아야”라고 불러주세요</h2><p>샘플 수집 {f.wake.n} / {f.wake.total} · 호출어만 짧고 또렷하게 불러주세요</p><MicLevelWaveform levels={micPreview.levels} />{f.wakeRejection && <p className={styles.rejection} role="status">{f.wakeRejection.reason}</p>}{micPreview.error && <p className={styles.error} role="status">{micPreview.error}</p>}</>, styles.wakeCenter)}{foot(btn('다음', () => send('voice_reg_start', {}, { step: 'voice', voiceTempId: null, voiceSentence: null, voiceCompleted: 0, voiceResult: null, finalVoiceReview: null }), !ready || !f.wakeDone))}</>; break;
    case 'voice': {
      const current = f.voiceSentence?.n ?? Math.min(f.voiceCompleted + 1, 5);
      content = <VoiceEnrollment mode="recording" current={current} total={5} sentence={sentences[current - 1] ?? '낭독 문장 원문을 기다리고 있습니다.'} micLevels={micPreview.levels} />; break;
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
    case 'micDone': content = done('마이크 설정', '마이크 설정 완료!', '목소리 등록이 완료되었습니다.', isMicOnly ? btn('설정으로 돌아가기', () => finishDeviceChange('mic')) : btn('다음 (카메라 설정)', () => go('gazeStart'))); break;
    case 'gazeStart': content = <><FrameTitle>시선 설정</FrameTitle>{center(<><p className={styles.lead}>시선 설정을 시작합니다</p><div className={styles.gazeStartGraphic} aria-hidden="true"><span className={styles.scopeOuter} /><span className={styles.scopeMiddle} /><span className={styles.scopeInner} /><i className={styles.scopeCross} /><b className={styles.scopeDot} /></div></>, styles.startCenter)}{foot(btn('시작하기', () => send('calib_start', {}, { step: 'position', precheck: null, point: null, result: null, poorCount: 0, gazeWaitingSince: Date.now(), gazeDelayed: false, pending: false }), !ready))}</>; break;
    case 'position': {
      const validPosition = Boolean(f.precheck?.face && f.precheck.distance === 'ok' && f.precheck.lighting === 'ok');
      content = <><FrameTitle>위치 확인</FrameTitle>{center(<div className={styles.cameraPreview}><span className={styles.cameraLive}>● CAMERA LIVE</span><div className={styles.personGuide}><i /><b /></div><p>머리와 어깨가 가이드 안에 들어오도록 위치해주세요</p><small>얼굴 {f.precheck ? (f.precheck.face ? '✓' : '확인 필요') : '확인 중'} · 거리 {f.precheck?.distance === 'ok' ? '✓' : '확인 필요'} · 조명 {f.precheck?.lighting === 'ok' ? '✓' : '확인 필요'}</small></div>, styles.positionCenter)}{f.gazeDelayed && <p className={styles.inlineNotice} role="status">위치 확인 응답이 지연되고 있습니다. 카메라 설정과 AI 상태를 확인해주세요.</p>}{foot(<>{btn('카메라 설정', cameraSettings, !connected, 'secondary')}{btn('다음', () => go('gazeGuide'), !ready || !validPosition)}</>)}</>; break;
    }
    case 'gazeGuide': content = <><FrameTitle>시선 측정</FrameTitle>{center(<><div className={styles.guideGraphic}>◎</div><h2>시선 측정을 시작하겠습니다</h2><p>화면에 나타나는 두더지의 코를 바라보면 됩니다.<br />화면과 60~80cm 거리를 유지하고 고개를 크게 움직이지 마세요.</p></>, styles.guideCenter)}{foot(<>{isCameraOnly && btn('취소', () => send('calib_cancel', {}, { step: 'gazeStart', pending: false }), !ready, 'secondary')}{btn('시작하기', () => measure(), !ready)}</>)}</>; break;
    case 'measuring': content = <GazeMeasurement point={f.point} ready={ready} />; break;
    case 'result': {
      const r = f.result; const poor = r.grade === 'poor'; const exhausted = f.poorCount >= 3 || r.remeasuresLeft === 0;
      const extent = Math.max(100, ...(r.points ?? []).flatMap((p) => [Math.abs(p.dx), Math.abs(p.dy)])) * 1.2;
      const average = r.avgErrorPx == null ? '미제공' : `${Math.round(r.avgErrorPx)}px`;
      const maximum = r.maxErrorPx == null ? '미제공' : `${Math.round(r.maxErrorPx)}px`;
      const errors = (r.points ?? []).map((point) => Math.hypot(Number(point.dx), Number(point.dy))).filter(Number.isFinite);
      const minimum = r.minErrorPx == null ? (errors.length ? `${Math.round(Math.min(...errors))}px` : '미제공') : `${Math.round(r.minErrorPx)}px`;
      content = <><FrameTitle>시선 측정 결과</FrameTitle>{center(<div className={styles.resultBoard}><span className={styles.cameraLive}>● CAMERA LIVE</span><div className={styles.plot}><svg viewBox={`${-extent} ${-extent} ${extent * 2} ${extent * 2}`} aria-label="목표점 기준 시선 오차 분포"><circle cx="0" cy="0" r={extent / 9} className={styles.guideCircle} /><circle cx="0" cy="0" r={extent / 40} className={styles.target} />{r.points?.map((p) => <circle key={p.n} cx={p.dx} cy={p.dy} r={extent / 30} />)}</svg></div><h2>최소 {minimum} · 평균 {average} · 최대 {maximum}</h2><strong>오차 범위 : {{ excellent: '우수', good: '양호', poor: '나쁨' }[r.grade] ?? '미제공'}</strong>{poor && <p>{exhausted ? '지속적으로 큰 오차가 발생했습니다. 카메라 설정을 다시 확인해주세요.' : '오차가 다소 큽니다. 시선을 다시 측정해주세요.'}</p>}</div>, styles.resultCenter)}{foot(<>{exhausted && poor ? btn('카메라 설정', cameraSettings, !connected) : btn('다시 측정', () => measure(true), !ready || !r.remeasuresLeft, 'secondary')}{!poor && btn('계속 진행', () => send('calib_commit', selectedDeviceLabel('camera') ? { deviceLabel: selectedDeviceLabel('camera') } : {}), !ready || r.pass !== true)}</>)}</>; break;
    }
    case 'gazeDone': content = done('시선 설정', '시선 설정 완료!', '시선 학습이 완료되었습니다.', isCameraOnly ? btn('설정으로 돌아가기', () => finishDeviceChange('camera')) : btn('다음', () => go('done'))); break;
    default: content = done('설정 완료', '완료!', '이제 SIA를 시작할 수 있습니다.', <Link className={styles.linkButton} to="/dashboard">완료</Link>);
  }
  const stepClassName = styles[`step_${f.step}`] ?? '';
  const wide = ['voice', 'voiceProcessing', 'voiceReview', 'position', 'gazeGuide', 'result'].includes(f.step);
  return <main className={styles.page}><section className={`${styles.card} ${wide ? styles.wideCard : ''} ${stepClassName}`} aria-label="첫 설정"><FrameChrome /><img className={styles.logo} src={logo} alt="SIA" />{content}<div className={styles.systemMessages}>{f.pending && <p role="status">서버 응답을 기다리고 있습니다.</p>}{f.request?.delayed && <p role="status">{f.request.type} 응답이 30초 이상 지연되고 있습니다. 연결 상태를 확인해주세요.</p>}{f.connectionError && <p className={styles.error} role="alert">{f.connectionError}</p>}{f.error && <p className={styles.error} role="alert">{f.error}</p>}{f.interrupted && btn('처음부터 다시 설정', () => { change({ interrupted: false }); go('welcome'); }, !connected, 'secondary')}</div></section><p className={styles.connection}>실시간 연결: {connected ? '연결됨' : '대기 중'} · AI: {f.status?.agentConnected ? '연결됨' : '대기 중'}</p></main>;
}
