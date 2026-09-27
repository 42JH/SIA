import { useEffect, useRef, useState } from 'react';
import httpClient from '../../api/httpClient';
import { voiceSampleUrl } from '../../api/profiles';
import { MIC_WAVE_BARS } from '../../hooks/useMicPreview';
import MicLevelWaveform from './MicLevelWaveform';
import styles from './VoiceEnrollment.module.css';

function silentBars() {
  return Array.from({ length: MIC_WAVE_BARS }, () => 0.08);
}

function RecordingView({ current, total, sentence, micLevels = [] }) {
  return <div className={styles.enrollment}>
    <h2 className={styles.title}>AI에게 명령하듯 말해보세요</h2>
    <p className={styles.count}>{current} / {total} 문장</p>
    <blockquote className={styles.sentence}>“{sentence}”</blockquote>
    <div className={styles.liveWave}><MicLevelWaveform levels={micLevels} /></div>
    <p className={styles.waiting} role="status">문장을 다 읽으면 자동으로 다음 문장으로 넘어갑니다.</p>
  </div>;
}

function ReviewView({ review, waveform = [], current, total, rejected, ready, pending, canRetry, canAccept, onRetry, onAccept, fullScreen, error }) {
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
    <ReviewPlayback review={review} durationLabel={durationLabel} waveform={waveform} />
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

function barsFromChannel(data) {
  const block = Math.max(1, Math.floor(data.length / MIC_WAVE_BARS));
  const peaks = Array.from({ length: MIC_WAVE_BARS }, (_, index) => {
    let peak = 0;
    const start = index * block;
    for (let offset = start; offset < start + block && offset < data.length; offset += 1) {
      peak = Math.max(peak, Math.abs(data[offset]));
    }
    return peak;
  });
  const max = Math.max(...peaks, 0.0001);
  return peaks.map((peak) => Math.min(1, Math.max(0.08, peak / max)));
}

async function loadSamplePeaks(path) {
  if (!path?.startsWith('/api/')) throw new Error('sample');
  const { data: bytes } = await httpClient.get(path, { responseType: 'arraybuffer' });
  const context = new AudioContext();
  try {
    if (context.state === 'suspended') await context.resume().catch(() => {});
    const buffer = await context.decodeAudioData(bytes.slice(0));
    return barsFromChannel(buffer.getChannelData(0));
  } finally {
    await context.close();
  }
}

function ReviewPlayback({ review, durationLabel, waveform = [] }) {
  const audioRef = useRef(null);
  const [playing, setPlaying] = useState(false);
  const [progress, setProgress] = useState(0);
  const [peaks, setPeaks] = useState(() => (waveform.length ? waveform : silentBars()));

  useEffect(() => () => {
    audioRef.current?.pause();
    audioRef.current = null;
  }, []);

  useEffect(() => {
    if (waveform.some((level) => level > 0.08)) {
      setPeaks(waveform);
      return undefined;
    }
    const path = review.sampleUrl;
    if (!path?.startsWith('/api/')) return undefined;
    let cancelled = false;
    loadSamplePeaks(path).then((next) => { if (!cancelled) setPeaks(next); }).catch(() => {});
    return () => { cancelled = true; };
  }, [review.sampleUrl, waveform]);

  useEffect(() => {
    if (!playing) return undefined;
    let frame;
    const tick = () => {
      const audio = audioRef.current;
      if (audio && audio.duration) setProgress(audio.currentTime / audio.duration);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing]);

  function toggle() {
    const source = voiceSampleUrl(review.sampleUrl);
    if (!source) return;
    const current = audioRef.current;
    if (current && playing) {
      current.pause();
      setPlaying(false);
      return;
    }
    if (current && !playing) {
      current.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
      return;
    }
    const audio = new Audio(source);
    const finish = () => {
      if (audioRef.current === audio) audioRef.current = null;
      setPlaying(false);
      setProgress(0);
    };
    audioRef.current = audio;
    setPlaying(true);
    audio.addEventListener('ended', finish, { once: true });
    audio.addEventListener('error', finish, { once: true });
    audio.play().catch(finish);
  }

  return <div className={styles.reviewAudio} aria-label="녹음된 음성 미리보기">
    <button type="button" className={styles.reviewPlayButton} onClick={toggle} disabled={!review.sampleUrl} aria-label={playing ? '일시정지' : '녹음된 음성 다시 듣기'}>
      {playing ? <span className={styles.pauseIcon} aria-hidden="true" /> : <svg className={styles.playIcon} viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l11-6.5Z" /></svg>}
    </button>
    <div className={`${styles.reviewWave} ${playing ? styles.reviewWaveActive : ''}`} aria-hidden="true">
      {peaks.map((level, index) => {
        const played = index / peaks.length <= progress;
        return <i key={index} className={played ? styles.reviewWavePlayed : undefined} style={{ height: `${Math.max(10, level * 100)}%` }} />;
      })}
    </div>
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
