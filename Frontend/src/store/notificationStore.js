import { create } from "zustand";
import { on } from "../ws/eventBus";

// 상단 알림 상태의 단일 진입점. WS 이벤트는 이 파일에서 화면용 상태로만 변환한다.
const AUTO_HIDE_MS = 3000;
const DETAIL_HIDE_MS = 5000;
const SUMMARY_HIDE_MS = 10000;
const CONFIRM_TIMEOUT_SEC = 12;
let hideTimer = null;

function sessionFallback(get) {
  const deadlineMs = get().sessionDeadlineMs;
  return deadlineMs && deadlineMs > Date.now()
    ? { kind: "session_countdown", deadlineMs }
    : null;
}

function clearHideTimer() {
  clearTimeout(hideTimer);
  hideTimer = null;
}

function scheduleAutoHide(set, get, delay = AUTO_HIDE_MS) {
  clearHideTimer();
  hideTimer = setTimeout(() => {
    set({ topNotification: sessionFallback(get) });
    hideTimer = null;
  }, delay);
}

function showTimed(set, get, notification, delay) {
  clearHideTimer();
  set({ topNotification: notification });
  scheduleAutoHide(set, get, delay);
}

export const useNotificationStore = create((set, get) => ({
  topNotification: null,
  sessionDeadlineMs: null,
  bootToastShown: false,

  showListening: () => {
    clearHideTimer();
    set({ topNotification: { kind: "listening" } });
  },

  showNotice: (data) => {
    const message = typeof data.message === "string" ? data.message : "";

    if (data.kind === "confirm") {
      clearHideTimer();
      set({
        topNotification: {
          kind: "confirm",
          message,
          // 확인 제한은 프로토콜 상수 12초. 서버 필드가 추가되면 그 값을 우선 사용한다.
          timeoutSec: data.timeoutSec ?? CONFIRM_TIMEOUT_SEC,
        },
      });
      return;
    }

    if (data.kind === "choices") {
      clearHideTimer();
      set({
        topNotification: {
          kind: "choices",
          message,
          choiceId: data.choiceId,
          choices: Array.isArray(data.choices) ? data.choices : [],
          timeoutSec: data.timeoutSec ?? CONFIRM_TIMEOUT_SEC,
        },
      });
      return;
    }

    if (data.kind === "unknown_command") {
      // TODO(BE): 3회 연속 실패 판정과 재등록 권유 문구를 AI가 보내는 계약 필요
      showTimed(set, get, {
        kind: "unknown_command",
        message,
        transcript: data.transcript,
      }, DETAIL_HIDE_MS);
      return;
    }

    // TODO(BE): progress/success/summary 표시는 현재 notice.kind 계약에 없어 AI·BE 계약 확정 필요
    if (data.kind === "progress") {
      clearHideTimer();
      set({ topNotification: { kind: "progress", message } });
      return;
    }

    if (data.kind === "summary" || Array.isArray(data.items)) {
      showTimed(set, get, {
        kind: "summary",
        message,
        items: Array.isArray(data.items)
          ? data.items.filter((item) => typeof item === "string")
          : [],
      }, SUMMARY_HIDE_MS);
      return;
    }

    showTimed(set, get, {
      kind: data.kind === "success" ? "success" : "notice",
      message,
    }, AUTO_HIDE_MS);
  },

  showToolResult: (data) => {
    // 제스처는 여러 스텝의 tool_result 뒤에 사용자 표시용 gesture_result가 따로 온다.
    if (data.caller === "GESTURE" || data.outcome === "EXECUTED" || !data.message) return;
    showTimed(set, get, { kind: "error", message: data.message }, DETAIL_HIDE_MS);
  },

  showGestureResult: (data) => {
    if (!data.message) return;
    showTimed(set, get, {
      kind: data.ok ? "success" : "error",
      message: data.message,
    }, AUTO_HIDE_MS);
  },

  showCaptureSaved: (data) => {
    clearHideTimer();
    set({
      topNotification: {
        kind: "capture_saved",
        path: data.path,
        url: data.url,
        width: data.width,
        height: data.height,
      },
    });
    scheduleAutoHide(set, get, DETAIL_HIDE_MS);
  },

  showVoiceRejected: (data) => {
    if (!data.message) return;
    showTimed(set, get, { kind: "voice_rejected", message: data.message }, AUTO_HIDE_MS);
  },

  showError: (data) => {
    if (!data.message) return;
    showTimed(set, get, { kind: "error", message: data.message, of: data.of }, DETAIL_HIDE_MS);
  },

  updateSession: (data) => {
    if (data.state === "ACTIVE" && data.deadlineMs) {
      set((state) => ({
        sessionDeadlineMs: data.deadlineMs,
        topNotification:
          !state.topNotification || state.topNotification.kind === "session_countdown"
            ? { kind: "session_countdown", deadlineMs: data.deadlineMs }
            : state.topNotification,
      }));
      return;
    }

    if (data.state === "PASSIVE") {
      clearHideTimer();
      set({ sessionDeadlineMs: null, topNotification: null });
    }
  },

  dismissNotification: () => {
    clearHideTimer();
    set({ topNotification: sessionFallback(get) });
  },

  triggerBootToast: () => {
    if (get().bootToastShown) return;
    set({ bootToastShown: true });
  },
}));

on("listening", () => useNotificationStore.getState().showListening());
on("notice", (data) => useNotificationStore.getState().showNotice(data));
on("tool_result", (data) => useNotificationStore.getState().showToolResult(data));
on("gesture_result", (data) => useNotificationStore.getState().showGestureResult(data));
on("capture_saved", (data) => useNotificationStore.getState().showCaptureSaved(data));
on("voice_rejected", (data) => useNotificationStore.getState().showVoiceRejected(data));
on("error", (data) => useNotificationStore.getState().showError(data));
on("session_state", (data) => {
  const store = useNotificationStore.getState();
  store.updateSession(data);
  if (data.state === "PASSIVE" && !data.reason) store.triggerBootToast();
});
