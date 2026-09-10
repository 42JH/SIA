import styles from './VoiceEnrollment.module.css';

function RecordingView({ current, total, sentence }) {
  return <div className={styles.enrollment}>
    <h2>AI에게 명령하듯 말해보세요</h2>
    <p className={styles.count}>{current} / {total} 문장</p>
    <blockquote className={styles.sentence}>“{sentence}”</blockquote>
    <p className={styles.waiting} role="status">음성을 판독하고 있습니다.</p>
  </div>;
}

function ReviewView({ review, current, total, rejected, ready, pending, canRetry, canAccept, onRetry, onAccept }) {
  const reason = review.reason?.trim() || '사유 미판정';
  return <div className={styles.enrollment}>
    <h2>{current} / {total} 문장 판독 결과</h2>
    <p className={styles.description}>{rejected ? reason : '판독 결과를 확인한 뒤 다음 문장으로 진행해주세요.'}</p>
    <div className={styles.quality}>
      <span>녹음 품질 · <strong>{review.quality?.trim() || '미판정'}</strong></span>
    </div>
    <div className={styles.actions}>
      <button onClick={onRetry} disabled={!ready || pending || !canRetry}>다시 녹음</button>
      {!rejected && <button className={styles.primary} onClick={onAccept} disabled={!ready || pending || !canAccept}>{current >= total ? '등록' : '다음 문장'}</button>}
    </div>
  </div>;
}

export default function VoiceEnrollment({ mode, ...props }) {
  return mode === 'review' ? <ReviewView {...props} /> : <RecordingView {...props} />;
}

export function VoiceProcessingView({ fullScreen = false, error }) {
  return <div className={`${styles.surface} ${fullScreen ? styles.fullScreen : ''}`}><div className={styles.content}>
    <div className={styles.spinner} aria-hidden="true" />
    <h2>녹음을 확인하고 있습니다</h2>
    <p>녹음 파일과 목소리 데이터를 준비하고 있습니다.</p>
    {error && <p className={styles.error} role="alert">{error}</p>}
  </div></div>;
}

export function VoiceReviewView({ sampleSrc, quality, noise, pending, canSubmit, error, onRetry, onSubmit, fullScreen = false }) {
  return <div className={`${styles.surface} ${fullScreen ? styles.fullScreen : ''}`}><div className={styles.content}>
    <h2>이 목소리로 등록할까요?</h2>
    <p>재생해 들어보고, 마음에 들지 않으면 다시 녹음할 수 있습니다.</p>
    {sampleSrc ? <audio className={styles.audio} controls src={sampleSrc} /> : <p>재생 가능한 샘플이 없습니다.</p>}
    <div className={styles.quality}><span>녹음 품질 · {quality ?? '미제공'}</span><span>주변 소음 {noise ?? '미제공'}</span></div>
    <div className={styles.actions}><button onClick={onRetry} disabled={pending}>다시 녹음</button><button className={styles.primary} onClick={onSubmit} disabled={!canSubmit || pending}>등록</button></div>
    {pending && <p role="status">서버 응답을 기다리고 있습니다.</p>}
    {error && <p className={styles.error} role="alert">{error}</p>}
  </div></div>;
}