package com.sia.assistant.mcp;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.LogPreview;
import com.sia.assistant.logging.ToolCallRecorder;
import com.sia.assistant.session.SessionService;
import java.util.Map;
import java.util.function.Supplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * 모든 도구 실행이 지나는 한 지점 — 세션 검사와 기록.
 *
 * <p>★ 확인 게이트는 여기 없다. 파괴적 도구의 사용자 동의는 <b>AI 가 도구를 부르기 전에</b> 받는다
 * (API.md §6.3). 카탈로그의 C 플래그는 BE 가 집행하는 관문이 아니라 <b>AI 에게 주는 선언</b>이고,
 * MCP 표준 {@code destructiveHint} 로 나간다. BE 는 승인이 끝난 요청으로 보고 그냥 실행한다.
 * 도구 메서드는 직접 DB 를 쓰지 않는다. 예외는 여기서 전부 ToolResult 로 환원되어 밖으로 나가지 않는다.
 * ★ 성공해도 세션을 자동 연장하지 않는다 — 연장은 session.extend 하나뿐이다.
 */
@Component
public class ToolGate {

    private static final Logger log = LoggerFactory.getLogger(ToolGate.class);

    private final SessionService sessionService;
    private final ToolCallRecorder recorder;

    public ToolGate(SessionService sessionService, ToolCallRecorder recorder) {
        this.sessionService = sessionService;
        this.recorder = recorder;
    }

    public ToolResult run(String tool, Map<String, Object> args, Caller caller, Supplier<Object> action) {
        long t0 = System.currentTimeMillis();
        Map<String, Object> safeArgs = args == null ? Map.of() : args;

        ToolCatalog.ToolSpec spec = ToolCatalog.spec(tool);
        if (spec == null) {
            // 카탈로그에 없는 이름은 기록 대상도 아니다 (tool_call.tool_name FK 가 tool 행을 요구한다)
            log.warn("[tool] {} caller={} args={} -> UNKNOWN", tool, caller, LogPreview.of(safeArgs.toString()));
            return ToolResult.failed("알 수 없는 도구입니다: " + tool);
        }

        Long sessionId = null;
        try {
            if (spec.sessionRequired()) {
                sessionId = sessionService.requireActive();
            } else {
                SessionService.Active active = sessionService.activeOrNull();
                sessionId = active == null ? null : active.id();
            }

            Object data = action.get();
            long ms = System.currentTimeMillis() - t0;
            log.info("[tool] {} caller={} args={} -> EXECUTED ({}ms)",
                    tool, caller, LogPreview.of(safeArgs.toString()), ms);
            recorder.record(tool, safeArgs, caller, "EXECUTED", null, sessionId, ms);
            return ToolResult.ok(data);

        } catch (BlockedException e) {
            long ms = System.currentTimeMillis() - t0;
            log.info("[tool] {} caller={} args={} -> BLOCKED {} ({}ms)",
                    tool, caller, LogPreview.of(safeArgs.toString()), e.code.name(), ms);
            recorder.record(tool, safeArgs, caller, "BLOCKED", e.getMessage(), sessionId, ms);
            return ToolResult.blocked(e.code.name(), e.getMessage());
        } catch (Exception e) {
            boolean invalidArgs = e instanceof ApiException api && api.code == ErrorCode.INVALID_REQUEST;
            String message = e instanceof ApiException api && api.getMessage() != null
                    ? api.getMessage()
                    : "도구 실행에 실패했습니다";
            String reason = e.getMessage() != null ? e.getMessage() : e.getClass().getSimpleName();
            // reason 은 FE tool_result.message 와 로그 화면에 그대로 나가는 사용자 문장이라, 원인은
            // 콘솔에만 덧붙인다. 이게 없으면 "파일을 열지 못했습니다" 한 줄만 남아 진단이 불가능하다.
            String detail = e instanceof ApiException api ? api.detail : null;
            long ms = System.currentTimeMillis() - t0;
            log.info("[tool] {} caller={} args={} -> FAILED {}{} ({}ms)",
                    tool, caller, LogPreview.of(safeArgs.toString()), reason,
                    detail == null || detail.isBlank() ? "" : " | " + detail, ms);
            // 인자 형식 오류도 정책 차단이 아니므로 outcome 은 FAILED 다 — 나뉘는 건 LLM 이 읽는 code 뿐이다.
            recorder.record(tool, safeArgs, caller, "FAILED", reason, sessionId, ms);
            return invalidArgs ? ToolResult.invalid(message) : ToolResult.failed(message);
        }
    }
}
