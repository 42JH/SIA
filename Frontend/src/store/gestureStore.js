import { create } from 'zustand';

const emptyRegistration = {
  stage: 'intro',
  motion: null,
  previewFrame: null,
  previewReady: false,
  tempId: null,
  phase: null,
  take: 0,
  takePhase: null,
  frame: null,
  completedTakes: [],
  previews: [],
  captured: false,
  selectedTake: 1,
  similarTo: null,
  similarity: null,
  error: '',
};

export const useGestureStore = create((set) => ({
  items: [],
  loading: false,
  error: '',
  registration: null,
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  setItems: (items) => set({ items }),
  patchItem: (id, patch) => set((state) => ({
    items: state.items.map((item) => item.id === id ? { ...item, ...patch } : item),
  })),
  removeItem: (id) => set((state) => ({ items: state.items.filter((item) => item.id !== id) })),
  beginRegistration: () => set({ registration: { ...emptyRegistration } }),
  updateRegistration: (patch) => set((state) => ({
    registration: state.registration ? { ...state.registration, ...patch } : state.registration,
  })),
  closeRegistration: () => set({ registration: null }),
}));
