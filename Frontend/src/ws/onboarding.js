import { on } from './eventBus';
import { sendFeMessage } from './feSocket';
import { useOnboardingStore } from '../store/onboardingStore';

const responses = {
  wakeword_enroll_start: ['wakeword_progress', 'wakeword_done'],
  voice_reg_start: ['voice_sentence', 'voice_reg_denied'],
  voice_sentence_next: ['voice_sentence'],
  voice_sentence_retry: ['voice_sentence'],
  voice_reg_retry: ['voice_sentence'],
  voice_accept_anyway: ['voice_review', 'voice_quality_warn'],
  voice_commit: ['voice_saved'],
  calib_start: ['calib_precheck', 'calib_point', 'calib_denied'],
  calib_point_shown: ['calib_point', 'calib_result'],
  calib_restart: ['calib_point', 'calib_limit'],
  calib_commit: ['calib_saved'],
};

export function sendOnboarding(type, data = {}) {
  if (type.startsWith('voice_') && type !== 'voice_reg_start' && !data.tempId) throw new Error('등록 식별자가 없어 요청을 보낼 수 없습니다.');
  if (!sendFeMessage(type, data)) throw new Error('실시간 연결을 기다린 후 다시 시도해주세요.');
  if (responses[type]) useOnboardingStore.getState().beginRequest(type, responses[type]);
  else useOnboardingStore.getState().change({ request: null });
}

export function subscribeOnboarding(handlers) {
  const subscriptions = Object.entries(handlers).map(([type, handler]) => on(type, (data) => {
    const state = useOnboardingStore.getState();
    if (state.interrupted && /^(wakeword_|voice_|calib_)/.test(type)) return;
    state.receiveEvent(type, data);
    handler(data);
  }));
  return () => subscriptions.forEach((unsubscribe) => unsubscribe());
}
