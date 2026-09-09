import { create } from "zustand";
import { on } from "../ws/eventBus";

// 세션 · WS 연결 상태 스토어 (agents.md 5장)
// WS로 받은 상태는 반드시 이 스토어의 액션을 통해서만 반영한다.
export const useSessionStore = create((set) => ({
  wsConnected: false,
  sessionState: null, // 최근 session_state 이벤트의 data 전체

  setWsConnected: (connected) => set({ wsConnected: connected }),
  setSessionState: (data) => set({ sessionState: data }),
}));

on("__connection__", (data) => {
  useSessionStore.getState().setWsConnected(data.status === "open");
});

on("session_state", (data) => {
  useSessionStore.getState().setSessionState(data);
});
