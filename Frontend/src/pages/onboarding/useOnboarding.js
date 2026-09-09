import { useEffect } from 'react';
import { fetchStatus } from '../../api/status';
import { subscribeOnboarding } from '../../ws/onboarding';
import { useOnboardingStore } from '../../store/onboardingStore';

const voiceSteps = ['voice', 'review'];
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
        if (status === 'closed' && ['wake', 'command', ...voiceSteps, ...gazeSteps].includes(state().step)) {
          change({ interrupted: true, pending: false, error: '연결이 끊겼습니다. 재연결 후 설정을 다시 시작해주세요.' });
        }
      },
      wakeword_progress: (wake) => { if (state().step === 'wake') change({ wake }); },
      wakeword_done: () => { if (state().step === 'wake') change({ wakeDone: true, pending: false }); },
      command_sentence: (commandSentence) => {
        if (state().step === 'command') change({ commandSentence, pending: false,
          error: commandSentence.total !== 5 ? '서버의 문장 수가 등록 기준 5문장과 다릅니다.' : '' });
      },
      command_progress: ({ n }) => { if (state().step === 'command') change({ commandCompleted: n }); },
      command_done: () => { if (state().step === 'command') change({ commandDone: true, pending: false }); },
      voice_sentence: (sentence) => {
        if (!voiceSteps.includes(state().step)) return;
        // TODO(BE): 보이스 시작 시 재시도·취소에 필요한 tempId를 FE에도 제공해야 함
        change({ sentence, step: 'voice', pending: false,
          error: sentence.total !== 5 ? '서버의 문장 수가 등록 기준 5문장과 다릅니다.' : '' });
      },
      voice_progress: ({ n }) => { if (state().step === 'voice') change({ completed: n }); },
      voice_quality_warn: (warning) => { if (voiceSteps.includes(state().step)) change({ warning, pending: false }); },
      voice_review: (review) => { if (voiceSteps.includes(state().step)) change({ review, step: 'review', pending: false }); },
      voice_saved: () => { if (state().step === 'review') change({ step: 'micDone', pending: false }); },
      voice_reg_denied: ({ message }) => { if (voiceSteps.includes(state().step)) change({ step: 'micStart', error: message, pending: false }); },
      calib_precheck: (precheck) => { if (gazeSteps.includes(state().step)) change({ precheck }); },
      calib_point: (point) => { if (gazeSteps.includes(state().step)) change({ point, pending: false }); },
      calib_result: (result) => { if (gazeSteps.includes(state().step)) state().receiveResult(result); },
      calib_saved: () => { if (state().step === 'result') change({ step: 'gazeDone', pending: false }); },
      calib_denied: ({ message }) => { if (gazeSteps.includes(state().step)) change({ step: 'gazeStart', error: message, pending: false }); },
      calib_limit: ({ message }) => change({ error: message, pending: false, result: state().result ? { ...state().result, remeasuresLeft: 0 } : null }),
      error: ({ message, of }) => {
        if (/^(voice_|command_|calib_|wakeword_)/.test(of ?? '')) change({ error: message, pending: false });
      },
    });
    return () => { disposed = true; clearTimeout(timer); stop(); };
  }, []);
}
