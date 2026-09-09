import { useEffect, useRef, useState } from 'react';
import styles from './DevicePreview.module.css';

export default function DevicePreview({ kind, deviceId }) {
  const element = useRef(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let disposed = false;
    let stream;
    let audio;
    let frame;
    setError('');
    const constraint = deviceId ? { deviceId: { exact: deviceId } } : true;
    navigator.mediaDevices.getUserMedia({ audio: kind === 'audio' ? constraint : false, video: kind === 'video' ? constraint : false }).then((media) => {
      if (disposed) { media.getTracks().forEach((track) => track.stop()); return; }
      stream = media;
      if (kind === 'video') { element.current.srcObject = media; return; }
      audio = new AudioContext();
      const analyser = audio.createAnalyser();
      analyser.fftSize = 256;
      audio.createMediaStreamSource(media).connect(analyser);
      const data = new Uint8Array(analyser.fftSize);
      const canvas = element.current;
      const context = canvas.getContext('2d');
      const draw = () => {
        if (disposed) return;
        analyser.getByteTimeDomainData(data);
        context.clearRect(0, 0, canvas.width, canvas.height);
        context.strokeStyle = getComputedStyle(canvas).color;
        context.beginPath();
        data.forEach((value, index) => {
          const x = index * canvas.width / data.length;
          const y = value / 255 * canvas.height;
          if (index === 0) context.moveTo(x, y); else context.lineTo(x, y);
        });
        context.stroke(); frame = requestAnimationFrame(draw);
      };
      audio.resume().then(draw).catch(() => setError('마이크 미리보기를 시작할 수 없습니다.'));
    }).catch(() => { if (!disposed) setError('장치 미리보기를 사용할 수 없습니다. 장치 권한과 다른 프로그램의 사용 여부를 확인해주세요.'); });
    return () => { disposed = true; cancelAnimationFrame(frame); stream?.getTracks().forEach((track) => track.stop()); audio?.close(); };
  }, [kind, deviceId]);
  return <div className={styles.preview}>{kind === 'video' ? <video ref={element} muted autoPlay playsInline /> : <canvas ref={element} width="500" height="90" aria-label="실제 마이크 입력 파형" />}{error && <p role="status">{error}</p>}</div>;
}
