import { useEffect, useRef, useState } from 'react';
import { startMicPreview, stopMicPreview, subscribeMicPreview } from '../ws/micPreview';

const BAR_COUNT = 32;
const silentLevels = () => Array.from({ length: BAR_COUNT }, () => 0.04);

export function useMicPreview(enabled) {
  const [levels, setLevels] = useState(silentLevels);
  const [phase, setPhase] = useState('STOPPED');
  const [error, setError] = useState('');
  const lastSeq = useRef(-1);

  useEffect(() => {
    if (!enabled) {
      setLevels(silentLevels());
      setPhase('STOPPED');
      setError('');
      return undefined;
    }

    lastSeq.current = -1;
    const unsubscribe = subscribeMicPreview({
      onLevel: ({ seq, level }) => {
        const nextSeq = Number(seq);
        const nextLevel = Number(level);
        if (!Number.isFinite(nextSeq) || !Number.isFinite(nextLevel) || nextSeq <= lastSeq.current) return;
        lastSeq.current = nextSeq;
        const normalized = Math.min(1, Math.max(0, nextLevel));
        setLevels((current) => [...current.slice(-(BAR_COUNT - 1)), normalized]);
      },
      onState: ({ phase: nextPhase, message }) => {
        setPhase(nextPhase ?? 'STOPPED');
        setError(nextPhase === 'ERROR' ? (message || '마이크 입력을 확인할 수 없습니다.') : '');
      },
      onError: ({ message }) => setError(message || '마이크 입력을 확인할 수 없습니다.'),
    });
    const started = startMicPreview();
    if (!started) setError('실시간 연결 후 마이크 입력을 확인할 수 있습니다.');

    return () => {
      unsubscribe();
      if (started) stopMicPreview();
    };
  }, [enabled]);

  return { levels, phase, error };
}
