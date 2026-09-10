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
