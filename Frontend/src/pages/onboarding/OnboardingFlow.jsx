import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchSettings, updateSettings } from '../../api/settings';
import { registerInstalledApps, sampleUrl } from '../../api/onboarding';
import { sendOnboarding } from '../../ws/onboarding';
import { useSessionStore } from '../../store/sessionStore';
import { useOnboardingStore } from '../../store/onboardingStore';
import { useOnboarding } from './useOnboarding';
import GazeMeasurement from '../../components/onboarding/GazeMeasurement';
import DevicePreview from '../../components/onboarding/DevicePreview';
import styles from './OnboardingHome.module.css';

const sentences = ['오늘 일정은 오전 열 시에 회의 하나만 남아 있어요.', '맑은 하늘 아래 강아지가 풀밭을 힘차게 뛰어다닙니다.', '바닷가 포장마차에서 따뜻한 어묵 국물을 마셨어요.'];

export default function OnboardingFlow() {
  useOnboarding();
  const f = useOnboardingStore();
  const connected = useSessionStore((s) => s.wsConnected);
  const [config, setConfig] = useState(null);
  const [devices, setDevices] = useState([]);
  const [name, setName] = useState('시아');
  const [mic, setMic] = useState('');
  const [camera, setCamera] = useState('');

  const ready = connected && f.status?.agentConnected && !f.interrupted;
  const change = f.change;
  const go = (step) => change({ step, pending: false, error: '' });
  const label = (id) => devices.find((d) => d.deviceId === id)?.label ?? null;
  async function run(action) {
    change({ pending: true, error: '' });
    try { await action(); } catch (error) { change({ pending: false, error: error.message }); }
  }
  function send(type, data = {}, patch = {}) {
    try { sendOnboarding(type, data); change({ pending: true, error: '', ...patch }); }
    catch (error) { change({ pending: false, error: error.message }); }
  }
  async function basic() {
    go('basic');
    await run(async () => { const data = await fetchSettings(); setConfig(data); setName(data.settings.wakeWord); change({ pending: false }); });
  }
  async function discover() {
    await run(async () => {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
      stream.getTracks().forEach((t) => t.stop());
      const list = await navigator.mediaDevices.enumerateDevices();
      setDevices(list.filter((d) => ['audioinput', 'videoinput'].includes(d.kind)));
      setMic(list.find((d) => d.kind === 'audioinput' && d.label === config?.settings.micDevice)?.deviceId ?? '');
      setCamera(list.find((d) => d.kind === 'videoinput' && d.label === config?.settings.cameraDevice)?.deviceId ?? '');
      change({ pending: false });
    });
  }
  async function save() {
    await run(async () => {
      try { setConfig(await updateSettings({ settings: { ...config.settings, wakeWord: name.trim(), micDevice: label(mic), cameraDevice: label(camera) }, updatedAt: config.updatedAt })); }
      catch (error) { if (error.code === 'SETTINGS_STALE') setConfig(await fetchSettings()); throw error; }
      await registerInstalledApps(); go('micStart');
    });
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
    case 'basic': content = <><h1>기본 설정</h1><div className={styles.fields}><label>비서 이름<input value={name} onChange={(e) => setName(e.target.value)} placeholder="예: SIA" /></label>{[['audioinput', '마이크 선택', mic, setMic], ['videoinput', '카메라 선택 (내장 / 외장)', camera, setCamera]].map(([kind, title, value, setter]) => <label key={kind}>{title}<select value={value} onChange={(e) => setter(e.target.value)}><option value="">시스템 기본 장치</option>{devices.filter((d) => d.kind === kind).map((d) => <option key={d.deviceId} value={d.deviceId}>{d.label}</option>)}</select></label>)}{btn('장치 접근 허용 · 목록 새로고침', discover)}{!config && btn('설정 다시 불러오기', basic)}</div>{foot(btn('다음', save, !config || !name.trim()))}</>; break;
    case 'micStart': content = <><h1>마이크 설정</h1>{center(<><h2>마이크 설정을 시작합니다</h2><div className={styles.icon}>♩</div></>)}{foot(<>{btn('건너뛰기', () => go('gazeStart'))}{btn('시작하기', () => send('wakeword_enroll_start', {}, { step: 'wake', wake: { n: 0, total: 10 }, wakeDone: false, pending: false }), !ready)}</>)}</>; break;
    case 'wake': content = <><h1>이름 불러보기</h1>{center(<><h2>"시아야" 라고 불러주세요</h2><DevicePreview kind="audio" deviceId={mic} /><progress value={f.wake.n} max={f.wake.total} /><p>샘플 수집 {f.wake.n} / {f.wake.total} · 또렷하게 불러주세요</p></>)}{foot(btn('다음', () => send('voice_reg_start', {}, { step: 'voice', sentence: null, completed: 0, warning: null, review: null }), !ready || !f.wakeDone))}</>; break;
    case 'voice': {
      const tempId = f.warning?.tempId ?? f.sentence?.tempId;
      content = center(<><h2>AI에게 명령하듯 말해보세요</h2><p>{f.completed} / 5 문장</p><blockquote>{sentences[(f.sentence?.n ?? 0) - 1] ?? '낭독 문장 원문을 기다리고 있습니다.'}</blockquote><DevicePreview kind="audio" deviceId={mic} /><progress value={f.completed} max={5} />
        {/* TODO(BE): 명령 수집과 화자 등록이 별도인 계약을 단일 5문장 등록 흐름에 맞춰야 함 */}
        {!tempId && <p>현재 서버는 녹음 시작 식별자를 제공하지 않아 재시도·중단을 사용할 수 없습니다.</p>}
        {f.warning && <p role="alert">{f.warning.reason}</p>}
        <div className={styles.actions}>{btn('이 문장 다시', () => send('voice_sentence_retry', { tempId }), !ready || !tempId)}{btn('중단', () => send('voice_reg_cancel', { tempId }, { step: 'micStart', pending: false }), !ready || !tempId)}{f.warning && btn('계속 진행', () => send('voice_accept_anyway', { tempId }), !ready)}</div></>); break;
    }
    case 'review': content = center(<><h2>이 목소리로 등록할까요?</h2><p>재생해 들어보고, 마음에 들지 않으면 다시 녹음할 수 있습니다.</p>{sampleUrl(f.review.sampleUrl) ? <audio controls src={sampleUrl(f.review.sampleUrl)} /> : <p>재생 가능한 샘플이 없습니다.</p>}<div className={styles.preview}>녹음 품질 · {f.review.quality ?? '미제공'} / 주변 소음 {f.review.noise ?? '미제공'}</div>{f.completed < 5 && <p role="alert">5문장 수집이 완료되지 않아 등록할 수 없습니다. 서버 계약 보완이 필요합니다.</p>}<div className={styles.actions}>{btn('다시 녹음', () => send('voice_reg_retry', { tempId: f.review.tempId }, { step: 'voice', completed: 0 }), !ready)}{btn('등록', () => send('voice_commit', { tempId: f.review.tempId, ...(label(mic) ? { deviceLabel: label(mic) } : {}) }), !ready || f.completed < 5)}</div></>); break;
    case 'micDone': content = done('마이크 설정', '목소리 등록이 완료되었습니다', btn('다음 (카메라 설정)', () => go('gazeStart'))); break;
    case 'gazeStart': content = <><h1>시선 설정</h1>{center(<><h2>시선 설정을 시작합니다</h2><div className={styles.icon}>◎</div></>)}{foot(btn('시작하기', () => send('calib_start', {}, { step: 'position', precheck: null, point: null, result: null, poorCount: 0, pending: false }), !ready))}</>; break;
    case 'position': content = <><h1>위치 확인</h1>{center(<><DevicePreview kind="video" deviceId={camera} /><p>앉아야 할 자리에 앉아주세요</p><p>자세 인식 중 · 가이드라인 안에 위치해주세요</p><p>얼굴: {f.precheck ? (f.precheck.face ? '인식됨' : '미인식') : '확인 중'} · 거리: {f.precheck?.distance ?? '확인 중'} · 조명: {f.precheck?.lighting ?? '확인 중'}</p></>)}{foot(btn('다음', () => go('gazeGuide'), !ready || !f.precheck?.face || f.precheck.distance !== 'ok' || f.precheck.lighting !== 'ok'))}</>; break;
    case 'gazeGuide': content = center(<><div className={styles.icon}>◎</div><h2>시선 측정을 시작하겠습니다</h2><p>화면에 튀어나오는 두더지의 코를 바라보면 됩니다.<br />약 1분 정도 걸립니다.</p><div className={styles.preview}>· 화면과 60~80cm 거리를 유지해주세요<br />· 보정 중에는 고개를 크게 움직이지 마세요<br />· 안경을 쓴다면 평소 사용하는 상태로 진행해주세요</div><div className={styles.actions}>{btn('취소', () => send('calib_cancel', {}, { step: 'gazeStart', pending: false }), !ready)}{btn('시작하기', () => measure(), !ready)}</div></>); break;
    case 'measuring': content = <GazeMeasurement point={f.point} ready={ready} onCancel={() => send('calib_cancel', {}, { step: 'gazeStart', pending: false })} />; break;
    case 'result': {
      const r = f.result; const poor = r.grade === 'poor'; const exhausted = f.poorCount >= 3 || r.remeasuresLeft === 0;
      const extent = Math.max(100, ...(r.points ?? []).flatMap((p) => [Math.abs(p.dx), Math.abs(p.dy)])) * 1.2;
      content = <><h1>시선 학습 결과</h1>{center(<><div className={styles.plot}><svg viewBox={`${-extent} ${-extent} ${extent * 2} ${extent * 2}`} aria-label="목표점 기준 시선 오차 분포"><circle cx="0" cy="0" r={extent / 40} className={styles.target} />{r.points?.map((p) => <circle key={p.n} cx={p.dx} cy={p.dy} r={extent / 30} />)}</svg><p>점: 목표 지점 · 원: 실제 측정된 시선 위치 (오차)</p></div><h2>오차 범위 : {{ excellent: '우수', good: '양호', poor: '나쁨' }[r.grade] ?? '미제공'}</h2>{poor && <p>{exhausted ? '지속적으로 큰 오차가 발생하고 있습니다. 카메라 설정을 확인한 후 다시 측정해주십시오.' : '오차가 다소 큽니다. 시선을 다시 측정해주세요.'}</p>}<p>남은 재측정: {r.remeasuresLeft}회</p></>)}{foot(<>{exhausted && poor ? btn('카메라 설정', () => send('calib_cancel', {}, { step: 'basic', pending: false }), !ready) : btn('다시 측정', () => measure(true), !ready || !r.remeasuresLeft)}{!poor && btn('계속 진행', () => send('calib_commit', label(camera) ? { deviceLabel: label(camera) } : {}), !ready || r.pass !== true)}</>)}</>; break;
    }
    case 'gazeDone': content = done('시선 설정', '시선 학습이 완료되었습니다', btn('다음', () => go('done'))); break;
    default: content = done('설정', '이제 SIA를 시작할 수 있습니다.', <Link className={styles.linkButton} to="/dashboard">완료</Link>);
  }
  return <main className={styles.page}><section className={styles.card} aria-label="첫 설정">{content}{f.pending && <p role="status">서버 응답을 기다리고 있습니다.</p>}{f.error && <p className={styles.error} role="alert">{f.error}</p>}{f.interrupted && btn('처음부터 다시 설정', () => { change({ interrupted: false }); go('welcome'); }, !connected)}</section><p className={styles.connection}>실시간 연결: {connected ? '연결됨' : '대기 중'} · AI: {f.status?.agentConnected ? '연결됨' : '대기 중'}</p></main>;
}


