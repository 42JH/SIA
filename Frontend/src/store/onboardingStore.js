import { create } from 'zustand';

const freshVoiceEnrollment = {
  wake: { n: 0, total: 5 }, wakeDone: false, wakeRejection: null,
  voiceTempId: null, voiceSentence: null, voiceCompleted: 0,
  voiceResult: null, finalVoiceReview: null,
};

export const useOnboardingStore = create((set) => ({
  step: 'welcome', status: null, error: '', connectionError: '', pending: false,
  request: null, lastEvent: null,
  wake: { n: 0, total: 5 }, wakeDone: false, wakeRejection: null,
  voiceTempId: null, voiceSentence: null, voiceCompleted: 0,
  voiceResult: null, finalVoiceReview: null,
  precheck: null, point: null, result: null, poorCount: 0,
  gazeWaitingSince: null, gazeDelayed: false,
  interrupted: false,
  change: (patch) => set(patch),
  resetVoiceEnrollment: (step = 'micStart') => set({
    ...freshVoiceEnrollment, step, pending: false, error: '', interrupted: false, request: null,
  }),
  beginRequest: (type, expected) => set({ request: { type, expected, sentAt: Date.now() } }),
  receiveEvent: (type, data) => set((state) => ({
    lastEvent: { type, at: Date.now() },
    ...(state.request?.expected.includes(type) || (type === 'error' && data.of === state.request?.type)
      ? { request: null, pending: false } : {}),
  })),
  interrupt: (message) => set({ interrupted: true, pending: false, request: null, error: message }),
  receiveResult: (result) => set((state) => ({
    result, step: 'result', pending: false,
    poorCount: result.grade === 'poor' ? state.poorCount + 1 : 0,
  })),
}));
