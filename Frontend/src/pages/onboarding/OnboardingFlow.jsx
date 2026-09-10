import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchSettings, updateSettings } from '../../api/settings';
import { fetchDevices } from '../../api/devices';
import { registerInstalledApps, sampleUrl } from '../../api/onboarding';
import { sendOnboarding } from '../../ws/onboarding';
import { useSessionStore } from '../../store/sessionStore';
import { useOnboardingStore } from '../../store/onboardingStore';
import { useOnboarding } from './useOnboarding';
import GazeMeasurement from '../../components/onboarding/GazeMeasurement';
import CommunicationLog from '../../components/onboarding/CommunicationLog';
import styles from './OnboardingHome.module.css';

import { ENROLLMENT_SENTENCES as sentences, WAKE_SAMPLE_SECONDS } from './enrollmentConstants';

export default function OnboardingFlow() {
  useOnboarding();
  const f = useOnboardingStore();
  const connected = useSessionStore((s) => s.wsConnected);
  const [config, setConfig] = useState(null);
  const [devices, setDevices] = useState({ mics: [], cameras: [] });
  const name = '시아';
  const [mic, setMic] = useState('');
  const [camera, setCamera] = useState('');
  const [cameraSettingsOnly, setCameraSettingsOnly] = useState(false);

  const ready = connected && f.status?.agentConnected && !f.interrupted;
  const change = f.change;
  const go = (step) => change({ step, pending: false, error: '' });
  const label = (id, kind) => devices[kind].find((d) => d.id === id)?.name ?? null;
  async function run(action) {
    change({ pending: true, error: '' });
    try { await action(); } catch (error) { change({ pending: false, error: error.message }); }
  }
  function send(type, data = {}, patch = {}) {
    try {
      sendOnboarding(type, data);
      change({ pending: true, error: '', ...patch,
        ...(type === 'voice_reg_start' ? { voiceTempId: null } : {}),
        ...(type === 'voice_reg_retry' ? { sentence: null, warning: null, review: null } : {}),
      });
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
    case 'micStart': content = <><h1>마이크 설정</h1>{center(<><h2>마이크 설정을 시작합니다</h2><div className={styles.icon}>♩</div></>)}{foot(<>{btn('건너뛰기', () => go('gazeStart'))}{btn('시작하기', () => send('wakeword_enroll_start', {}, { step: 'wake', wake: { n: 0, total: 10 }, wakeDone: false, pending: false }), !ready)}</>)}</>; break;
    case 'wake': content = <><h1>이름 불러보기</h1>{center(<><h2>"시아야" 라고 불러주세요</h2><p>샘플 수집 {f.wake.n} / {f.wake.total} · 한 번에 약 {WAKE_SAMPLE_SECONDS}초 안에 또렷하게 불러주세요</p></>)}{foot(btn('다음', () => send('command_enroll_start', {}, { step: 'command', commandSentence: null, commandCompleted: 0, commandDone: false }), !ready || !f.wakeDone))}</>; break;
    case 'command': content = center(<><h2>AI에게 명령하듯 말해보세요</h2><p>명령 문장 수집 · {f.commandCompleted} / 5 문장</p><blockquote>{sentences[(f.commandSentence?.n ?? 0) - 1] ?? '문장 수집 준비를 기다리고 있습니다.'}</blockquote>{btn('다음 (목소리 등록)', () => send('voice_reg_start', {}, { step: 'voice', sentence: null, completed: 0, warning: null, review: null }), !ready || !f.commandDone || f.commandCompleted < 5)}</>); break;
    case 'voice': {
      const tempId = f.voiceTempId;
      content = center(<><h2>AI에게 명령하듯 말해보세요</h2><p>{f.completed} / 5 문장</p><blockquote>{sentences[(f.sentence?.n ?? 0) - 1] ?? '문장 수집 준비를 기다리고 있습니다.'}</blockquote>
        {/* 명령 문장 수집 후 같은 원문으로 보이스 프로필 등록 진행 */}
        {!tempId && <p>문장 수집은 계속 진행됩니다. 등록 식별자를 받기 전에는 이 문장 다시·중단을 사용할 수 없습니다.</p>}
        {f.warning && <p role="alert">{f.warning.reason}</p>}
        <div className={styles.actions}>{btn('이 문장 다시', () => send('voice_sentence_retry', { tempId }), !ready || !tempId)}{btn('중단', () => send('voice_reg_cancel', { tempId }, { step: 'micStart', pending: false }), !ready || !tempId)}{f.warning && btn('계속 진행', () => send('voice_accept_anyway', { tempId }), !ready || !tempId)}</div></>); break;
    }
    case 'review': content = center(<><h2>이 목소리로 등록할까요?</h2><p>재생해 들어보고, 마음에 들지 않으면 다시 녹음할 수 있습니다.</p>{sampleUrl(f.review.sampleUrl) ? <audio controls src={sampleUrl(f.review.sampleUrl)} /> : <p>재생 가능한 샘플이 없습니다.</p>}<div className={styles.preview}>녹음 품질 · {f.review.quality ?? '미제공'} / 주변 소음 {f.review.noise ?? '미제공'}</div>{!f.voiceTempId && <p role="status">등록 식별자를 받지 못해 저장·다시 녹음을 사용할 수 없습니다.</p>}{f.completed < 5 && <p role="alert">5문장 수집이 완료되지 않아 등록할 수 없습니다. 서버 계약 보완이 필요합니다.</p>}<div className={styles.actions}>{btn('다시 녹음', () => send('voice_reg_retry', { tempId: f.voiceTempId }, { step: 'voice', completed: 0 }), !ready || !f.voiceTempId)}{btn('등록', () => send('voice_commit', { tempId: f.voiceTempId, ...(label(mic, 'mics') ? { deviceLabel: label(mic, 'mics') } : {}) }), !ready || !f.voiceTempId || f.completed < 5)}</div></>); break;
    case 'micDone': content = done('마이크 설정', '목소리 등록이 완료되었습니다', btn('다음 (카메라 설정)', () => go('gazeStart'))); break;
    case 'gazeStart': content = <><h1>시선 설정</h1>{center(<><h2>시선 설정을 시작합니다</h2><div className={styles.icon}>◎</div></>)}{foot(btn('시작하기', () => send('calib_start', {}, { step: 'position', precheck: null, point: null, result: null, poorCount: 0, gazeWaitingSince: Date.now(), gazeDelayed: false, pending: false }), !ready))}</>; break;
    case 'position': content = <><h1>위치 확인</h1>{center(<><p>앉아야 할 자리에 앉아주세요</p><p>화면을 정면으로 바라보고 바른 자세로 앉아주세요</p><p>서버 확인값 — 얼굴: {f.precheck ? (f.precheck.face ? '인식됨' : '미인식') : '확인 중'} · 거리: {f.precheck?.distance ?? '확인 중'} · 조명: {f.precheck?.lighting ?? '확인 중'}</p></>)}{f.gazeDelayed && <p role="status">위치 확인 응답이 지연되고 있습니다. 카메라 설정과 AI 상태를 확인해주세요.</p>}{foot(<>{btn('카메라 설정', cameraSettings, !connected)}{btn('취소', () => send('calib_cancel', {}, { step: 'gazeStart', gazeWaitingSince: null, gazeDelayed: false, pending: false }), !connected)}{btn('다음', () => go('gazeGuide'), !ready || !f.point || !f.precheck?.face || f.precheck.distance !== 'ok' || f.precheck.lighting !== 'ok')}</>)}</>; break;
    case 'gazeGuide': content = center(<><div className={styles.icon}>◎</div><h2>시선 측정을 시작하겠습니다</h2><p>화면에 튀어나오는 두더지의 코를 바라보면 됩니다.<br />약 1분 정도 걸립니다.</p><div className={styles.preview}>· 화면과 60~80cm 거리를 유지해주세요<br />· 보정 중에는 고개를 크게 움직이지 마세요<br />· 안경을 쓴다면 평소 사용하는 상태로 진행해주세요</div><div className={styles.actions}>{btn('취소', () => send('calib_cancel', {}, { step: 'gazeStart', pending: false }), !ready)}{btn('시작하기', () => measure(), !ready)}</div></>); break;
    case 'measuring': content = <GazeMeasurement point={f.point} ready={ready} connected={connected} onCancel={() => send('calib_cancel', {}, { step: 'gazeStart', pending: false })} />; break;
    case 'result': {
      const r = f.result; const poor = r.grade === 'poor'; const exhausted = f.poorCount >= 3 || r.remeasuresLeft === 0;
      const extent = Math.max(100, ...(r.points ?? []).flatMap((p) => [Math.abs(p.dx), Math.abs(p.dy)])) * 1.2;
      content = <><h1>시선 학습 결과</h1>{center(<><div className={styles.plot}><svg viewBox={`${-extent} ${-extent} ${extent * 2} ${extent * 2}`} aria-label="목표점 기준 시선 오차 분포"><circle cx="0" cy="0" r={extent / 40} className={styles.target} />{r.points?.map((p) => <circle key={p.n} cx={p.dx} cy={p.dy} r={extent / 30} />)}</svg><p>점: 목표 지점 · 원: 실제 측정된 시선 위치 (오차)</p></div><h2>오차 범위 : {{ excellent: '우수', good: '양호', poor: '나쁨' }[r.grade] ?? '미제공'}</h2>{poor && <p>{exhausted ? '지속적으로 큰 오차가 발생하고 있습니다. 카메라 설정을 확인한 후 다시 측정해주십시오.' : '오차가 다소 큽니다. 시선을 다시 측정해주세요.'}</p>}<p>남은 재측정: {r.remeasuresLeft}회</p></>)}{foot(<>{exhausted && poor ? btn('카메라 설정', cameraSettings, !connected) : btn('다시 측정', () => measure(true), !ready || !r.remeasuresLeft)}{!poor && btn('계속 진행', () => send('calib_commit', label(camera, 'cameras') ? { deviceLabel: label(camera, 'cameras') } : {}), !ready || r.pass !== true)}</>)}</>; break;
    }
    case 'gazeDone': content = done('시선 설정', '시선 학습이 완료되었습니다', btn('다음', () => go('done'))); break;
    default: content = done('설정', '이제 SIA를 시작할 수 있습니다.', <Link className={styles.linkButton} to="/dashboard">완료</Link>);
  }
  return <main className={styles.page}><section className={styles.card} aria-label="첫 설정">{content}{f.pending && <p role="status">서버 응답을 기다리고 있습니다.</p>}{f.request?.delayed && <p role="status">{f.request.type} 응답이 30초 이상 지연되고 있습니다. 통신 기록을 확인해주세요. 응답이 도착하면 계속 진행합니다.</p>}{f.connectionError && <p className={styles.error} role="alert">{f.connectionError}</p>}{f.error && <p className={styles.error} role="alert">{f.error}</p>}{f.interrupted && btn('처음부터 다시 설정', () => { change({ interrupted: false }); go('welcome'); }, !connected)}</section><p className={styles.connection}>실시간 연결: {connected ? '연결됨' : '대기 중'} · AI: {f.status?.agentConnected ? '연결됨' : '대기 중'}</p><CommunicationLog /></main>;
}







