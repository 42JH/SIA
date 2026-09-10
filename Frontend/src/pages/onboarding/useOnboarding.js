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
    const active = () => ['wake', 'command', ...voiceSteps, ...gazeSteps].includes(state().step);
    const state = () => useOnboardingStore.getState();
    const change = (patch) => state().change(patch);
    async function poll() {
      try {
        const status = await fetchStatus();
        if (!disposed) {
          if (state().status?.agentConnected && !status.agentConnected && active()) state().interrupt('AI 연결이 끊겼습니다. 연결 복구 후 설정을 다시 시작해주세요.');
          change({ status, connectionError: '' });
        }
      } catch (error) {
        if (!disposed) change({ status: null, connectionError: error.message });
      }
      if (!disposed) timer = setTimeout(poll, 3000);
    }
    poll();
    const watchdog = setInterval(() => {
      const gaze = state();
      if (gaze.step === 'position' && gaze.gazeWaitingSince && !gaze.gazeDelayed && Date.now() - gaze.gazeWaitingSince > 30000) {
        change({ gazeDelayed: true });
      }
      const request = state().request;
      if (request && !request.delayed && Date.now() - request.sentAt > 30000) {
        change({ request: { ...request, delayed: true } });
      }
    }, 1000);
    const stop = subscribeOnboarding({
      __connection__: ({ status }) => {
        if (status === 'closed' && ['wake', 'command', ...voiceSteps, ...gazeSteps].includes(state().step)) {
          state().interrupt('연결이 끊겼습니다. 재연결 후 설정을 다시 시작해주세요.');
        }
      },
      agent_status: ({ connected }) => {
        if (!connected && active()) state().interrupt('AI 연결이 끊겼습니다. 연결 복구 후 설정을 다시 시작해주세요.');
        change({ status: { ...state().status, agentConnected: connected } });
      },
      settings_sync: (data) => change({ status: { ...state().status, ...data, settingsPending: data.agentSyncedVersion == null || data.agentSyncedVersion < data.settingsVersion } }),
      wakeword_progress: (wake) => {
        if (state().step !== 'wake') return;
        const n = Math.min(Math.max(Number(wake.n) || 0, 0), 5);
        change({ wake: { n, total: 5 }, ...(n >= 5 ? { wakeDone: true, pending: false } : {}) });
      },
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
        change({ sentence, voiceTempId: sentence.tempId ?? state().voiceTempId, warning: null, step: 'voice', pending: false,
          error: sentence.total !== 5 ? '서버의 문장 수가 등록 기준 5문장과 다릅니다.' : '' });
      },
      voice_progress: ({ n, tempId }) => { if (state().step === 'voice') change({ completed: n, voiceTempId: tempId ?? state().voiceTempId }); },
      voice_quality_warn: (warning) => { if (voiceSteps.includes(state().step)) change({ warning, voiceTempId: warning.tempId ?? state().voiceTempId, pending: false }); },
      voice_review: (review) => { if (voiceSteps.includes(state().step)) change({ review, voiceTempId: review.tempId ?? state().voiceTempId, step: 'review', pending: false }); },
      voice_saved: () => { if (state().step === 'review') change({ step: 'micDone', pending: false }); },
      voice_reg_denied: ({ message }) => { if (voiceSteps.includes(state().step)) change({ step: 'micStart', error: message, pending: false }); },
      // TODO(BE): AI가 새 보정마다 precheck를 재전송해야 함. 거리·조명의 실측 여부도 서버에서 제공 필요
      calib_precheck: (precheck) => { if (gazeSteps.includes(state().step)) change({ precheck, gazeWaitingSince: null, gazeDelayed: false }); },
      calib_point: (point) => { if (gazeSteps.includes(state().step)) change({ point, pending: false }); },
      calib_result: (result) => { if (gazeSteps.includes(state().step)) state().receiveResult(result); },
      calib_saved: () => { if (state().step === 'result') change({ step: 'gazeDone', pending: false }); },
      calib_denied: ({ message }) => { if (gazeSteps.includes(state().step)) change({ step: 'gazeStart', error: message, pending: false }); },
      calib_limit: ({ message }) => change({ error: message, pending: false, result: state().result ? { ...state().result, remeasuresLeft: 0 } : null }),
      error: ({ message, of }) => {
        if (/^(voice_|command_|calib_|wakeword_)/.test(of ?? '')) change({ error: message, pending: false });
      },
    });
    return () => { disposed = true; clearTimeout(timer); clearInterval(watchdog); stop(); };
  }, []);
}
