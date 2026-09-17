import { useEffect } from 'react';
import { fetchStatus } from '../../api/status';
import { subscribeOnboarding } from '../../ws/onboarding';
import { useOnboardingStore } from '../../store/onboardingStore';

const voiceSteps = ['voice', 'voiceProcessing', 'voiceReview'];
const gazeSteps = ['position', 'gazeGuide', 'measuring', 'result'];
const voiceRejectionMessages = {
  TOO_SHORT: '너무 짧게 들렸어요. 문장을 끝까지 읽어주세요.',
  TOO_LONG: '너무 길게 들렸어요. 화면의 문장 하나만 읽어주세요.',
  NOISY: '주변이 시끄러워요. 조용한 곳에서 다시 읽어주세요.',
  INCONSISTENT: '앞 문장과 목소리가 다르게 들려요. 같은 분이 조용한 곳에서 다시 읽어주세요.',
};

export function useOnboarding() {
  useEffect(() => {
    let disposed = false;
    let timer;
    const state = () => useOnboardingStore.getState();
    const active = () => ['wake', ...voiceSteps, ...gazeSteps].includes(state().step);
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
        if (status === 'closed' && ['wake', ...voiceSteps, ...gazeSteps].includes(state().step)) {
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
        change({ wake: { n, total: 5 }, wakeRejection: null, pending: false });
      },
      wakeword_rejected: (rejection) => {
        if (state().step !== 'wake') return;
        const expected = Math.min(state().wake.n + 1, 5);
        if (Number(rejection.n) !== expected) return;
        const reason = typeof rejection.reason === 'string' ? rejection.reason.trim() : '';
        change({ wakeRejection: { code: rejection.code ?? null, reason: reason || '제대로 녹음되지 않았습니다. 다시 불러주세요.' }, pending: false });
      },
      wakeword_done: () => { if (state().step === 'wake') change({ wakeDone: true, wakeRejection: null, pending: false }); },
      voice_sentence: (voiceSentence) => {
        if (!voiceSteps.includes(state().step)) return;
        change({
          voiceSentence,
          voiceTempId: voiceSentence.tempId,
          ...(state().step === 'voice' ? { pending: false } : {}),
          error: voiceSentence.total !== 5 ? '서버의 문장 수가 등록 기준 5문장과 다릅니다.' : '',
        });
      },
      voice_progress: (voiceProgress) => {
        if (!voiceSteps.includes(state().step)) return;
        change({
          voiceTempId: voiceProgress.tempId,
          voiceCompleted: Number(voiceProgress.n) || 0,
          voiceResult: { ...voiceProgress, rejected: false },
          pending: false,
        });
      },
      voice_sentence_rejected: (rejection) => {
        if (!voiceSteps.includes(state().step)) return;
        const tempId = state().voiceTempId;
        if (!rejection.tempId || rejection.tempId !== tempId) return;
        const currentN = Number(state().voiceSentence?.n) || Math.min(state().voiceCompleted + 1, 5);
        const rejectedN = Number(rejection.n);
        if (rejectedN !== currentN) return;
        const reason = (voiceRejectionMessages[rejection.code]
          ?? (typeof rejection.reason === 'string' ? rejection.reason.trim() : ''))
          || '제대로 녹음되지 않았습니다. 같은 문장을 다시 읽어주세요.';
        change({
          voiceResult: {
            ...rejection,
            tempId,
            n: rejectedN,
            total: Number(rejection.total) || 5,
            reason,
            rejected: true,
          },
          finalVoiceReview: null,
          step: 'voiceReview',
          pending: false,
        });
      },
      voice_quality_warn: (warning) => {
        if (!voiceSteps.includes(state().step)) return;
        const n = Math.max(1, state().voiceCompleted);
        change({
          voiceTempId: warning.tempId,
          voiceResult: { ...warning, n, total: 5, rejected: true },
          finalVoiceReview: null,
          step: 'voiceReview',
          pending: false,
        });
      },
      voice_review: (review) => {
        if (!voiceSteps.includes(state().step)) return;
        // 문장 하나가 끝날 때마다 오며 문장 번호가 없으므로 누적된 진행 수를 사용한다.
        const n = Math.min(Math.max(1, state().voiceCompleted), 5);
        change({
          voiceTempId: review.tempId,
          finalVoiceReview: n >= 5 ? review : null,
          voiceResult: { ...state().voiceResult, ...review, n, total: 5, rejected: false },
          step: 'voiceReview',
          pending: false,
        });
      },
      voice_saved: () => { if (voiceSteps.includes(state().step)) change({ step: 'micDone', pending: false, request: null }); },
      voice_reg_denied: ({ message }) => { if (voiceSteps.includes(state().step)) change({ step: 'micStart', error: message, pending: false }); },
      // TODO(BE): AI가 새 보정마다 precheck를 재전송해야 함. 거리·조명의 실측 여부도 서버에서 제공 필요
      calib_precheck: (precheck) => { if (gazeSteps.includes(state().step)) change({ precheck, gazeWaitingSince: null, gazeDelayed: false }); },
      calib_point: (point) => { if (gazeSteps.includes(state().step)) change({ point, pending: false }); },
      calib_result: (result) => { if (gazeSteps.includes(state().step)) state().receiveResult(result); },
      calib_saved: () => { if (state().step === 'result') change({ step: 'gazeDone', pending: false }); },
      calib_denied: ({ message }) => { if (gazeSteps.includes(state().step)) change({ step: 'gazeStart', error: message, pending: false }); },
      calib_limit: ({ message }) => change({ error: message, pending: false, result: state().result ? { ...state().result, remeasuresLeft: 0 } : null }),
      error: ({ message, of }) => {
        if (/^(voice_|calib_|wakeword_)/.test(of ?? '')) change({ error: message, pending: false });
      },
    });
    return () => { disposed = true; clearTimeout(timer); clearInterval(watchdog); stop(); };
  }, []);
}
