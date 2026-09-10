import { on } from './eventBus';
import { sendFeMessage } from './feSocket';

function send(type, data = {}) {
  if (!sendFeMessage(type, data)) throw new Error('실시간 연결을 기다린 후 다시 시도해주세요.');
}

export const startGestureRegistration = () => send('reg_start', {});
export const finishGestureRecording = (tempId) => send('reg_stop', { tempId });
export const assignGestureMacro = (data) => send('macro_assign', data);

export function subscribeGestures(handlers) {
  const subscriptions = Object.entries(handlers).map(([type, handler]) => on(type, handler));
  return () => subscriptions.forEach((unsubscribe) => unsubscribe());
}
