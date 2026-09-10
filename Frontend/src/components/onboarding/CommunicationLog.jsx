import { useCommunicationStore } from '../../store/communicationStore';
import { useOnboardingStore } from '../../store/onboardingStore';
import styles from './CommunicationLog.module.css';

export default function CommunicationLog() {
  const entries = useCommunicationStore((s) => s.entries);
  const clear = useCommunicationStore((s) => s.clear);
  const request = useOnboardingStore((s) => s.request);
  return <details className={styles.panel}><summary>통신 기록 ({entries.length})</summary>
    {request && <p>응답 대기: {request.type} → {request.expected.join(' / ')}</p>}
    <p>발신은 FE 전송 기록이며 AI 수신·처리 성공을 뜻하지 않습니다.</p>
    <button onClick={clear}>기록 비우기</button>
    <ol>{entries.map((entry) => <li key={entry.id}><strong>{entry.at.slice(11, 23)} UTC · {entry.channel} {entry.direction} · {entry.type}</strong><pre>{JSON.stringify(entry.data, null, 2)}</pre></li>)}</ol>
  </details>;
}
