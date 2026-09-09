import { create } from "zustand";
import { on } from "../ws/eventBus";

// 상단 알림(TopNotification) · 우측하단 부팅 토스트(BootToast) 상태 스토어 (agents.md 5장)
// 이벤트-화면 매핑은 대화로 확정한 표를 그대로 따른다.
// WS로 받은 상태는 반드시 이 스토어의 액션을 통해서만 반영한다.

const AUTO_HIDE_MS = 3000;
let hideTimer = null;
let unknownCommandCount = 0; // 연속 명령 실패 카운트 (agents.md 4.3 표 참고, 서버 값 아님)

function scheduleAutoHide(set) {
  clearTimeout(hideTimer);
  hideTimer = setTimeout(() => set({ topNotification: null }), AUTO_HIDE_MS);
}

export const useNotificationStore = create((set, get) => ({
  topNotification: null, // {kind, ...} 또는 null
  bootToastShown: false,

  showListening: () => {
    clearTimeout(hideTimer);
    set({ topNotification: { kind: "listening" } });
  },

  // session_state ACTIVE 진입 시 명령 처리 대기 구간을 로컬로 표시
  // (서버 이벤트가 아니라 FE 추정 상태이므로, 다음 결과 이벤트가 오면 바로 교체된다)
  showExecuting: () => {
    clearTimeout(hideTimer);
    set((prev) =>
      prev.topNotification?.kind === "executing" ? prev : { topNotification: { kind: "executing" } }
    );
  },

  showNotice: (data) => {
    if (data.kind === "confirm") {
      clearTimeout(hideTimer);
      unknownCommandCount = 0;
      set({
        topNotification: {
          kind: "confirm",
          message: data.message,
          timeoutSec: data.timeoutSec ?? 10, // 확인 Timeout 10초 확정 (FR/NFR 문서)
        },
      });
      return;
    }

    if (data.kind === "unknown_command") {
      unknownCommandCount += 1;
      clearTimeout(hideTimer);
      set({
        topNotification: {
          kind: "unknown_command",
          transcript: data.transcript,
          message:
            unknownCommandCount >= 3
              ? // TODO(BE): 3회 연속 실패 시 안내 문구가 명세에 확정돼 있지 않음. 임시 문구.
                "카메라 · 마이크 설정을 다시 확인해보시겠어요?"
              : data.message,
        },
      });
      return;
    }

    // 그 외 일반 notice (완료 안내, 요약 등)
    unknownCommandCount = 0;
    clearTimeout(hideTimer);
    // TODO(BE): 요약 결과가 message 외 추가 필드(예: summary 배열)로 오는지 미확정.
    // 지금은 message 문자열만 그대로 표시한다.
    set({ topNotification: { kind: "notice", message: data.message } });
    scheduleAutoHide(set);
  },

  showToolResult: (data) => {
    if (data.tool === "files.delete" && data.outcome === "EXECUTED") {
      unknownCommandCount = 0;
      clearTimeout(hideTimer);
      set({
        topNotification: {
          kind: "file_deleted",
          message: `'${data.path ?? ""}' 파일을 삭제하였습니다.`,
        },
      });
      scheduleAutoHide(set);
    }
    // 그 외 tool_result는 지금 단계에서 별도 팝업을 띄우지 않는다 (필요 시 notice로 옴)
  },

  showVoiceRejected: (data) => {
    unknownCommandCount = 0;
    clearTimeout(hideTimer);
    set({ topNotification: { kind: "voice_rejected", message: data.message } });
    scheduleAutoHide(set);
  },

  // ACTIVE 세션 남은 시간 표시 (FR-022: BE가 준 deadlineMs 기준으로 FE가 계산)
  updateSessionCountdown: (data) => {
    if (!data.deadlineMs) return;
    set((prev) =>
      !prev.topNotification || prev.topNotification.kind === "session_countdown"
        ? { topNotification: { kind: "session_countdown", deadlineMs: data.deadlineMs } }
        : prev
    );
  },

  clearSessionCountdown: () => {
    set((prev) =>
      prev.topNotification?.kind === "session_countdown" ? { topNotification: null } : {}
    );
  },

  triggerBootToast: () => {
    if (get().bootToastShown) return; // 최초 1회만
    set({ bootToastShown: true });
  },
}));

// --- WS 구독 등록 ---

on("listening", () => useNotificationStore.getState().showListening());

on("notice", (data) => useNotificationStore.getState().showNotice(data));

on("tool_result", (data) => useNotificationStore.getState().showToolResult(data));

on("voice_rejected", (data) => useNotificationStore.getState().showVoiceRejected(data));

on("session_state", (data) => {
  const store = useNotificationStore.getState();
  if (data.state === "ACTIVE") {
    store.showExecuting();
    store.updateSessionCountdown(data);
    return;
  }
  if (data.state === "PASSIVE") {
    store.clearSessionCountdown();
    if (!data.reason) {
      // reason 없는 PASSIVE = AI 부팅 완료 통지, 앱 켤 때 한 번만 온다
      store.triggerBootToast();
    }
  }
});
