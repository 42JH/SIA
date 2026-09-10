import { create } from 'zustand';

// 진단 기록은 메모리에만 보관하며 내부 오류 상세·바이너리는 제외
function clean(value, key = '') {
  if (['detail', 'jpegB64', 'npz', 'sample'].includes(key)) return '[생략]';
  if (typeof value === 'string') return value.length > 1000 ? `${value.slice(0, 1000)}…` : value;
  if (Array.isArray(value)) return value.slice(0, 20).map((item) => clean(item));
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, clean(v, k)]));
  return value;
}

let sequence = 0;
export const useCommunicationStore = create((set) => ({
  entries: [],
  record: (channel, direction, type, data) => set((state) => ({
    entries: [{ id: ++sequence, at: new Date().toISOString(), channel, direction, type, data: clean(data) }, ...state.entries].slice(0, 150),
  })),
  clear: () => set({ entries: [] }),
}));
