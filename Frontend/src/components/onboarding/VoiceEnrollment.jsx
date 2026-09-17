import styles from './VoiceEnrollment.module.css';
import MicLevelWaveform from './MicLevelWaveform';

function RecordingView({ current, total, sentence, fullScreen, micLevels = [] }) {
  return <div className={`${styles.enrollment} ${fullScreen ? styles.fullScreen : ''}`}>
    <h2>AI에게 명령하듯 말해보세요</h2>
    <p className={styles.count}>{current} / {total} 문장</p>
    <blockquote className={styles.sentence}>“{sentence}”</blockquote>
    <MicLevelWaveform levels={micLevels} />
    <p className={styles.waiting} role="status">문장을 다 읽으면 자동으로 다음 문장으로 넘어갑니다.</p>
  </div>;
}

function ReviewView({ review, current, total, rejected, ready, pending, canRetry, canAccept, onRetry, onAccept, fullScreen, error }) {
  const reason = review.reason?.trim() || '사유 미판정';
  const finalReview = current >= total && !rejected;
  return <div className={`${styles.enrollment} ${fullScreen ? styles.fullScreen : ''}`}>
    <h2>{finalReview ? '이 목소리로 등록할까요?' : `${current} / ${total} 문장 판독 결과`}</h2>
    <p className={styles.description}>{rejected ? reason : finalReview ? '마음에 들지 않으면 다시 녹음할 수 있습니다.' : '판독 결과를 확인한 뒤 다음 문장으로 진행해주세요.'}</p>
    <div className={styles.quality}>
      <span>녹음 품질 · <strong>{review.quality?.trim() || '미판정'}</strong></span>
    </div>
    <div className={styles.actions}>
      <button onClick={onRetry} disabled={!ready || pending || !canRetry}>다시 녹음</button>
      {!rejected && <button className={styles.primary} onClick={onAccept} disabled={!ready || pending || !canAccept}>{current >= total ? '등록' : '다음 문장'}</button>}
    </div>
    {error && <p className={styles.error} role="alert">{error}</p>}
  </div>;
}

export default function VoiceEnrollment({ mode, ...props }) {
  if (mode === 'processing') return <ProcessingView {...props} />;
  return mode === 'review' ? <ReviewView {...props} /> : <RecordingView {...props} />;
}

function ProcessingView({ fullScreen = false, error }) {
  return <div className={`${styles.enrollment} ${fullScreen ? styles.fullScreen : ''}`}>
    <div className={styles.spinner} aria-hidden="true" />
    <h2>녹음을 확인하고 있습니다</h2>
    <p>녹음 파일과 목소리 데이터를 준비하고 있습니다.</p>
    {error && <p className={styles.error} role="alert">{error}</p>}
  </div>;
}
