import { create } from 'zustand';

const initialState = {
  step: 'start',
  status: null,
  precheck: null,
  point: null,
  result: null,
  poorCount: 0,
  restartPending: false,
  savedCalib: null,
  pending: false,
  delayed: false,
  failed: false,
  error: '',
};

export const useGazeCalibrationStore = create((set) => ({
  ...initialState,
  change: (patch) => set(patch),
  reset: () => set(initialState),
  receiveResult: (result) => set((state) => ({
    result,
    step: 'result',
    pending: false,
    restartPending: false,
    poorCount: result.grade === 'poor' ? state.poorCount + 1 : state.poorCount,
  })),
}));
