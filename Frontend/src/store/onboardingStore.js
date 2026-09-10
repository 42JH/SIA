import { create } from 'zustand';

export const useOnboardingStore = create((set) => ({
  step: 'welcome', status: null, error: '', pending: false,
  wake: { n: 0, total: 10 }, wakeDone: false,
  commandSentence: null, commandCompleted: 0, commandReview: null, commandDone: false,
  precheck: null, point: null, result: null, poorCount: 0,
  interrupted: false,
  change: (patch) => set(patch),
  receiveResult: (result) => set((state) => ({
    result, step: 'result', pending: false,
    poorCount: result.grade === 'poor' ? state.poorCount + 1 : 0,
  })),
}));
