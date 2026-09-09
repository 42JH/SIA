import { on } from './eventBus';
import { sendFeMessage } from './feSocket';

export function sendOnboarding(type, data = {}) {
  if (!sendFeMessage(type, data)) throw new Error('실시간 연결을 기다린 후 다시 시도해주세요.');
}

export function subscribeOnboarding(handlers) {
  const subscriptions = Object.entries(handlers).map(([type, handler]) => on(type, handler));
  return () => subscriptions.forEach((unsubscribe) => unsubscribe());
}
