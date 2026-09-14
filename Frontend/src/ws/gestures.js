import { on } from './eventBus';
import { sendFeMessage } from './feSocket';

function send(type, data = {}) {
  if (!sendFeMessage(type, data)) throw new Error('실시간 연결을 기다린 후 다시 시도해주세요.');
}

export const startGestureRegistration = (motion) => send('reg_start', { motion });
export const finishGestureRecording = (tempId) => send('reg_stop', { tempId });
export const assignGestureMacro = (data) => send('macro_assign', data);
export const startGesturePreview = () => send('cam_preview_start', {});
export const stopGesturePreview = () => send('cam_preview_stop', {});

export function subscribeGestures(handlers) {
  const subscriptions = Object.entries(handlers).map(([type, handler]) => on(type, handler));
  return () => subscriptions.forEach((unsubscribe) => unsubscribe());
}
