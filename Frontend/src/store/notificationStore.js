import { create } from "zustand";
import { on } from "../ws/eventBus";

// 상단 알림 상태의 단일 진입점. WS 이벤트는 이 파일에서 화면용 상태로만 변환한다.
const AUTO_HIDE_MS = 3000;
const DETAIL_HIDE_MS = 5000;
const SUMMARY_HIDE_MS = 10000;
const CONFIRM_TIMEOUT_SEC = 10;
const CHOICE_TIMEOUT_SEC = 12;
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

let lastToast = { key: '', at: 0 };

function noticeKey(message) {
  return String(message || '')
    .replace(/\s+/g, '')
    .replace(/[."'`’“”!?~…·]/g, '')
    .replace(/했습니다|입니다|습니다|었습니다|됐습니다|되었습니다|됩니다|됐어요|해요|예요/g, '');
}

function similarNotice(a, b) {
  if (!a || !b) return false;
  if (a === b) return true;
  return a.length >= 8 && b.length >= 8 && (a.includes(b) || b.includes(a));
}

function isSameNotice(current, next) {
  const b = noticeKey(next?.message);
  if (!b) return false;
  if (similarNotice(noticeKey(current?.message), b)) return true;
  return similarNotice(lastToast.key, b) && Date.now() - lastToast.at < 4000;
}

function showTimed(set, get, notification, delay) {
  if (isSameNotice(get().topNotification, notification)) {
    scheduleAutoHide(set, get, delay);
    return;
  }
  lastToast = { key: noticeKey(notification.message), at: Date.now() };
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
          // 삭제 확인 표시는 사용자 확정 기준 10초로 고정
          timeoutSec: CONFIRM_TIMEOUT_SEC,
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
          timeoutSec: data.timeoutSec ?? CHOICE_TIMEOUT_SEC,
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

    // 새로 전달된 요약 팝업 사용 확정
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

const unsubNotify = [
  on("listening", () => useNotificationStore.getState().showListening()),
  on("notice", (data) => useNotificationStore.getState().showNotice(data)),
  on("tool_result", (data) => useNotificationStore.getState().showToolResult(data)),
  on("gesture_result", (data) => useNotificationStore.getState().showGestureResult(data)),
  on("capture_saved", (data) => useNotificationStore.getState().showCaptureSaved(data)),
  on("voice_rejected", (data) => useNotificationStore.getState().showVoiceRejected(data)),
  on("error", (data) => useNotificationStore.getState().showError(data)),
  on("session_state", (data) => {
    const store = useNotificationStore.getState();
    store.updateSession(data);
    if (data.state === "PASSIVE" && !data.reason) store.triggerBootToast();
  }),
];
if (import.meta.hot) import.meta.hot.dispose(() => unsubNotify.forEach((unsub) => unsub()));
