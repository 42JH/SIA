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
    const active = () => ['wake', ...commandSteps, ...gazeSteps].includes(state().step);
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
        if (status === 'closed' && ['wake', ...commandSteps, ...gazeSteps].includes(state().step)) {
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
        if (!commandSteps.includes(state().step)) return;
        change({
          commandSentence,
          ...(state().step === 'command' ? { pending: false } : {}),
          error: commandSentence.total !== 5 ? '서버의 문장 수가 등록 기준 5문장과 다릅니다.' : '',
        });
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
