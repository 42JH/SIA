import { on } from './eventBus';
import { sendFeMessage } from './feSocket';

const gazeEventTypes = [
  '__connection__',
  'agent_status',
  'settings_sync',
  'calib_precheck',
  'calib_point',
  'calib_result',
  'calib_limit',
  'calib_saved',
  'calib_denied',
  'error',
];

export function sendGazeCalibration(type, data = {}) {
  if (!sendFeMessage(type, data)) throw new Error('실시간 연결을 기다린 후 다시 시도해주세요.');
}

export function subscribeGazeCalibration(handlers) {
  const subscriptions = gazeEventTypes.map((type) => on(type, (data) => handlers[type]?.(data)));
  return () => subscriptions.forEach((unsubscribe) => unsubscribe());
}
