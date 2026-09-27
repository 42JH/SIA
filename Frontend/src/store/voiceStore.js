import { create } from 'zustand';

const initialEnrollment = {
  stage: 'list', tempId: null, sentence: null, completed: 0, total: 5,
  warning: null, review: null, pending: false, error: '',
};

export const useVoiceStore = create((set) => ({
  ...initialEnrollment,
  change: (patch) => set(patch),
  resetEnrollment: () => set(initialEnrollment),
  receiveSentence: (sentence) => set((state) => ({
    stage: 'recording', sentence, tempId: sentence.tempId ?? state.tempId,
    total: sentence.total ?? state.total,
    warning: null, review: null, pending: false, error: '',
  })),
  receiveProgress: ({ n, total, tempId }) => set((state) => ({
    completed: n, total: total ?? state.total, tempId: tempId ?? state.tempId,
    stage: n >= (total ?? state.total) ? 'processing' : state.stage, pending: false,
  })),
  receiveWarning: (warning) => set((state) => ({
    stage: 'warning', warning, tempId: warning.tempId ?? state.tempId, pending: false, error: '',
  })),
  receiveReview: (review) => set((state) => ({
    stage: 'review', review, tempId: review.tempId ?? state.tempId, pending: false, error: '',
  })),
  receiveSentenceRejected: (rejection) => set((state) => ({
    stage: 'review', review: { ...rejection, rejected: true },
    tempId: rejection.tempId ?? state.tempId, pending: false, error: '',
  })),
  receiveSaved: () => set({ stage: 'done', pending: false, error: '' }),
}));
