import { useEffect, useRef, useState } from 'react';
import { voiceSampleUrl } from '../../api/profiles';
import styles from './VoiceEnrollment.module.css';

function RecordingView({ current, total, sentence }) {
  return <div className={styles.enrollment}>
    <h2 className={styles.title}>AI에게 명령하듯 말해보세요</h2>
    <p className={styles.count}>{current} / {total} 문장</p>
    <blockquote className={styles.sentence}>“{sentence}”</blockquote>
    <p className={styles.waiting} role="status">문장을 다 읽으면 자동으로 다음 문장으로 넘어갑니다.</p>
    <div className={styles.voiceTarget} aria-hidden="true"><span /><i /><strong>음성 감지 중</strong></div>
  </div>;
}

function ReviewView({ review, current, total, rejected, ready, pending, canRetry, canAccept, onRetry, onAccept, fullScreen, error }) {
  const reason = review.reason?.trim() || '제대로 녹음되지 않았습니다. 같은 문장을 다시 읽어주세요.';
  const finalReview = current >= total && !rejected;
  const durationSeconds = review.durationSec != null && Number.isFinite(Number(review.durationSec))
    ? Math.max(0, Math.round(Number(review.durationSec)))
    : review.durationMs != null && Number.isFinite(Number(review.durationMs))
      ? Math.max(0, Math.round(Number(review.durationMs) / 1000))
      : null;
  const durationLabel = durationSeconds == null ? '--:--' : `${String(Math.floor(durationSeconds / 60)).padStart(2, '0')}:${String(durationSeconds % 60).padStart(2, '0')}`;
  return <div className={`${styles.enrollment} ${fullScreen ? styles.fullScreen : ''}`}>
    <h2 className={styles.title}>{finalReview ? '이 목소리로 등록할까요?' : `${current} / ${total} 문장 판독 결과`}</h2>
    <p className={styles.description}>{rejected ? reason : finalReview ? '마음에 들지 않으면 다시 녹음할 수 있습니다.' : '판독 결과를 확인한 뒤 다음 문장으로 진행해주세요.'}</p>
    <ReviewPlayback review={review} durationLabel={durationLabel} />
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

function ReviewPlayback({ review, durationLabel }) {
  const audioRef = useRef(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => () => audioRef.current?.pause(), []);

  function replay() {
    const source = voiceSampleUrl(review.sampleUrl);
    if (!source || playing) return;
    const audio = new Audio(source);
    const finish = () => {
      if (audioRef.current === audio) audioRef.current = null;
      setPlaying(false);
    };
    audioRef.current = audio;
    setPlaying(true);
    audio.addEventListener('ended', finish, { once: true });
    audio.addEventListener('error', finish, { once: true });
    audio.play().catch(finish);
  }

  return <div className={styles.reviewAudio} aria-label="녹음된 음성 미리보기">
    <button type="button" className={styles.reviewMicButton} onClick={replay} disabled={!review.sampleUrl} aria-label={playing ? '녹음된 음성 재생 중' : '녹음된 음성 다시 듣기'}>
      <div className={styles.reviewMic}><span /><i /></div>
    </button>
    <div className={styles.reviewWave}>{Array.from({ length: 20 }, (_, index) => <i key={index} />)}</div>
    <time>{durationLabel}</time>
  </div>;
}

export default function VoiceEnrollment({ mode, ...props }) {
  if (mode === 'processing') return <ProcessingView {...props} />;
  return mode === 'review' ? <ReviewView {...props} /> : <RecordingView {...props} />;
}

function ProcessingView({ fullScreen = false, error }) {
  return <div className={`${styles.enrollment} ${fullScreen ? styles.fullScreen : ''}`}>
    <div className={styles.spinner} aria-hidden="true" />
    <h2 className={styles.title}>녹음을 확인하고 있습니다</h2>
    <p>녹음 파일과 목소리 데이터를 준비하고 있습니다.</p>
    {error && <p className={styles.error} role="alert">{error}</p>}
  </div>;
}
