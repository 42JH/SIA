import { on } from './eventBus';
import { sendFeMessage } from './feSocket';

export function startMicPreview() {
  return sendFeMessage('mic_preview_start', {});
}

export function stopMicPreview() {
  return sendFeMessage('mic_preview_stop', {});
}

export function subscribeMicPreview({ onLevel, onState, onError }) {
  const subscriptions = [
    on('mic_preview_level', onLevel),
    on('mic_preview_state', onState),
    on('error', (data) => {
      if (data.of === 'mic_preview_start' || data.of === 'mic_preview_stop') onError(data);
    }),
  ];
  return () => subscriptions.forEach((unsubscribe) => unsubscribe());
}
