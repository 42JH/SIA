import { on } from './eventBus';
import { sendFeMessage } from './feSocket';

function send(type, data = {}) {
  if (!sendFeMessage(type, data)) throw new Error('실시간 연결을 기다린 후 다시 시도해주세요.');
}

// TODO(BE): reg_start captureType(STATIC/DYNAMIC) 분기와 정적 사진 3회 촬영 계약 추가 필요
export const startGestureRegistration = (captureType) => send('reg_start', { captureType });
export const finishGestureRecording = (tempId) => send('reg_stop', { tempId });
export const assignGestureMacro = (data) => send('macro_assign', data);
// TODO(BE): AI 카메라 대기 미리보기 시작·종료·프레임 중계 이벤트 구현 필요
export const startGesturePreview = () => send('cam_preview_start', {});
export const stopGesturePreview = () => send('cam_preview_stop', {});

export function subscribeGestures(handlers) {
  const subscriptions = Object.entries(handlers).map(([type, handler]) => on(type, handler));
  return () => subscriptions.forEach((unsubscribe) => unsubscribe());
}
