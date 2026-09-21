import logo from '../../assets/sia-logo.png';
import dashboardStyles from '../dashboard/DashboardHome.module.css';
import voiceStyles from '../dashboard/VoicePanel.module.css';
import styles from './OnboardingWakeView.module.css';

export default function OnboardingWakeView({
  step,
  wakeDone,
  wake,
  enrollWakeWord,
  rejection,
  micLevels,
  micError,
  canStart,
  pending,
  error,
  connectionError,
  delayed,
  onStart,
  onCancel,
  onFinish,
}) {
  const done = wakeDone || step === 'micDone';
  const total = 5;
  const completed = Math.min(total, Math.max(0, Number(wake?.n) || 0));
  const current = done ? total : completed;
  let body;
  if (done) {
    body = <div className={voiceStyles.completeState}><span>✓</span><h2>호출명 학습이 완료되었습니다</h2><p>호출명이 변경되었습니다.</p><button className={voiceStyles.primary} onClick={onFinish}>설정으로 돌아가기</button></div>;
  } else if (step === 'wake') {
    body = completed >= total ? <div className={voiceStyles.centerState}>
      <div className={voiceStyles.spinner} />
      <h2>새 호출명을 저장하고 있습니다</h2>
      <p>설정에 반영되는 즉시 완료 화면으로 이동합니다.</p>
    </div> : <div className={voiceStyles.recordingContent}>
      <div className={voiceStyles.recordMeta}><strong>{current} / {total} 샘플</strong></div>
      <blockquote>“{enrollWakeWord}”라고 불러주세요</blockquote>
      <div className={voiceStyles.liveAudio}><span><MicIcon compact /></span><Wave levels={micLevels} /><strong>음성 감지 중</strong></div>
      {rejection && <p className={styles.error} role="status">{rejection}</p>}
      {micError && <p className={styles.error} role="status">{micError}</p>}
      <p className={styles.sampleNotice}>완료 {completed} / {total} · 총 5번 불러주세요</p>
      <div className={voiceStyles.actionRow}><button onClick={onCancel} disabled={pending}>취소</button></div>
    </div>;
  } else {
    body = <div className={voiceStyles.guideContent}>
      <div className={voiceStyles.enrollmentMic}><div className={voiceStyles.enrollmentMicCircle}><MicIcon /></div></div>
      <h2>호출명을 등록합니다</h2>
      <p>마이크 등록은 주변 소음이 적은 조용한 환경에서<br />진행하는 것을 권장합니다.<br />약 30초 정도 걸립니다.</p>
      <button className={voiceStyles.primary} onClick={onStart} disabled={!canStart || pending}>시작하기</button>
      <div className={voiceStyles.actionRow}><button onClick={onCancel} disabled={pending}>취소</button></div>
    </div>;
  }

  return <main className={`${dashboardStyles.page} ${dashboardStyles.view_wake}`}>
    <header className={dashboardStyles.header}><button className={dashboardStyles.brand} onClick={onCancel} aria-label="설정으로 돌아가기"><img src={logo} alt="SIA" /></button><span /></header>
    <section className={dashboardStyles.content}>
      <section className={voiceStyles.registrationPage}>
        <header className={voiceStyles.voiceHero}>
          <div className={voiceStyles.heroTitle}><button onClick={onCancel} aria-label="이전 화면으로 돌아가기" /><h1>호출명 변경</h1></div>
          <svg className={voiceStyles.circuit} viewBox="0 0 760 120" preserveAspectRatio="none" aria-hidden="true"><circle cx="14" cy="66" r="5" /><path d="M19 66h190l44 30h249l54-42h174" /><path className={voiceStyles.circuitLight} d="M350 35h170l42-19h150" /></svg>
        </header>
        <div className={voiceStyles.registrationStage}>
          <section className={styles.wakeStage}>
            {body}
            {pending && <p className={styles.status} role="status">서버 응답을 기다리고 있습니다.</p>}
            {delayed && <p className={styles.status} role="status">응답이 30초 이상 지연되고 있습니다. 연결 상태를 확인해주세요.</p>}
            {connectionError && <p className={styles.error} role="alert">{connectionError}</p>}
            {error && <p className={styles.error} role="alert">{error}</p>}
          </section>
        </div>
      </section>
    </section>
  </main>;
}

function Wave({ levels }) {
  const heights = levels?.length ? levels.map((level) => Math.max(10, level * 100)) : Array.from({ length: 32 }, () => 12);
  return <div className={voiceStyles.wave} aria-hidden="true">{heights.map((height, index) => <i style={{ height: `${height}%` }} key={index} />)}</div>;
}

function MicIcon({ compact = false }) {
  return <svg className={`${voiceStyles.micIcon} ${compact ? voiceStyles.compactMic : ''}`} viewBox="0 0 120 120" aria-hidden="true"><rect x="44" y="19" width="32" height="56" rx="16" /><path d="M30 64v4c0 19 12 31 30 31s30-12 30-31v-4M60 99v15M43 114h34" /></svg>;
}
