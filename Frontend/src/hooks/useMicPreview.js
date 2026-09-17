import { useEffect, useRef, useState } from 'react';
import { startMicPreview, stopMicPreview, subscribeMicPreview } from '../ws/micPreview';

export const MIC_WAVE_BARS = 48;
const silentLevels = () => Array.from({ length: MIC_WAVE_BARS }, () => 0.04);

function downsampleEnvelope(samples, count = MIC_WAVE_BARS) {
  if (!samples.length) return silentLevels();
  const peaks = Array.from({ length: count }, (_, index) => {
    const start = Math.floor((index * samples.length) / count);
    const end = Math.max(start + 1, Math.floor(((index + 1) * samples.length) / count));
    let peak = 0;
    for (let offset = start; offset < end; offset += 1) peak = Math.max(peak, samples[offset] ?? 0);
    return peak;
  });
  const max = Math.max(...peaks, 0.12);
  return peaks.map((peak) => Math.min(1, Math.max(0.08, peak / max)));
}

export function useMicPreview(enabled, resetKey) {
  const [levels, setLevels] = useState(silentLevels);
  const [envelope, setEnvelope] = useState(silentLevels);
  const [phase, setPhase] = useState('STOPPED');
  const [error, setError] = useState('');
  const lastSeq = useRef(-1);
  const epoch = useRef(0);
  const historyRef = useRef([]);

  useEffect(() => {
    if (!enabled) return undefined;
    if (historyRef.current.length) setEnvelope(downsampleEnvelope(historyRef.current));
    epoch.current += 1;
    lastSeq.current = -1;
    historyRef.current = [];
    setLevels(silentLevels());
    return undefined;
  }, [enabled, resetKey]);

  useEffect(() => {
    if (!enabled) {
      if (historyRef.current.length) setEnvelope(downsampleEnvelope(historyRef.current));
      epoch.current += 1;
      historyRef.current = [];
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
        const captured = epoch.current;
        if (!Number.isFinite(nextSeq) || !Number.isFinite(nextLevel) || nextSeq <= lastSeq.current) return;
        lastSeq.current = nextSeq;
        const normalized = Math.min(1, Math.max(0, nextLevel));
        historyRef.current.push(normalized);
        setEnvelope(downsampleEnvelope(historyRef.current));
        setLevels((current) => (captured !== epoch.current ? current : [...current.slice(-(MIC_WAVE_BARS - 1)), normalized]));
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

  return { levels, envelope, phase, error };
}
