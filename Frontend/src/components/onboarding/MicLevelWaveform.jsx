import styles from './MicLevelWaveform.module.css';

export default function MicLevelWaveform({ levels, label = '음성 감지 중' }) {
  return <div className={styles.preview} role="img" aria-label={label}>
    <div className={styles.bars} aria-hidden="true">{levels.map((level, index) => <i key={index} style={{ height: `${Math.max(10, level * 100)}%` }} />)}</div>
    <strong>{label}</strong>
  </div>;
}
