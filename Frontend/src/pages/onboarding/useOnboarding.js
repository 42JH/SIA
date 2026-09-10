import { useEffect } from 'react';
import { fetchStatus } from '../../api/status';
import { subscribeOnboarding } from '../../ws/onboarding';
import { useOnboardingStore } from '../../store/onboardingStore';

const commandSteps = ['command', 'commandReview'];
const gazeSteps = ['position', 'gazeGuide', 'measuring', 'result'];

export function useOnboarding() {
  useEffect(() => {
    let disposed = false;
    let timer;
    const state = () => useOnboardingStore.getState();
    const change = (patch) => state().change(patch);
    async function poll() {
      try {
        const status = await fetchStatus();
        if (!disposed) change({ status });
      } catch (error) {
        if (!disposed) change({ status: null, error: error.message });
      }
      if (!disposed) timer = setTimeout(poll, 3000);
    }
    poll();
    const stop = subscribeOnboarding({
      __connection__: ({ status }) => {
        if (status === 'closed' && ['wake', ...commandSteps, ...gazeSteps].includes(state().step)) {
          change({ interrupted: true, pending: false, error: '연결이 끊겼습니다. 재연결 후 설정을 다시 시작해주세요.' });
        }
      },
      wakeword_progress: (wake) => { if (state().step === 'wake') change({ wake }); },
      wakeword_done: () => { if (state().step === 'wake') change({ wakeDone: true, pending: false }); },
      command_sentence: (commandSentence) => {
        if (!commandSteps.includes(state().step)) return;
        change({ commandSentence, ...(state().step === 'command' ? { pending: false } : {}) });
      },
      command_progress: (result) => {
        if (!commandSteps.includes(state().step)) return;
        change({ commandCompleted: result.n, commandReview: { ...result, rejected: false }, step: 'commandReview', pending: false });
      },
      command_rejected: (result) => {
        if (!commandSteps.includes(state().step)) return;
        change({ commandReview: { ...result, rejected: true }, step: 'commandReview', pending: false });
      },
      command_done: () => { if (commandSteps.includes(state().step)) change({ commandDone: true, pending: false }); },
      calib_precheck: (precheck) => { if (gazeSteps.includes(state().step)) change({ precheck }); },
      calib_point: (point) => { if (gazeSteps.includes(state().step)) change({ point, pending: false }); },
      calib_result: (result) => { if (gazeSteps.includes(state().step)) state().receiveResult(result); },
      calib_saved: () => { if (state().step === 'result') change({ step: 'gazeDone', pending: false }); },
      calib_denied: ({ message }) => { if (gazeSteps.includes(state().step)) change({ step: 'gazeStart', error: message, pending: false }); },
      calib_limit: ({ message }) => change({ error: message, pending: false, result: state().result ? { ...state().result, remeasuresLeft: 0 } : null }),
      error: ({ message, of }) => {
        if (/^(command_|voice_sentence_retry|calib_|wakeword_)/.test(of ?? '')) change({ error: message, pending: false });
      },
    });
    return () => { disposed = true; clearTimeout(timer); stop(); };
  }, []);
}
