package com.sia.assistant.mcp.tools;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.sia.assistant.control.screen.CaptureService;
import com.sia.assistant.logging.ToolCallRecorder;
import com.sia.assistant.mcp.Caller;
import com.sia.assistant.mcp.RefResolver;
import com.sia.assistant.mcp.ToolGate;
import com.sia.assistant.mcp.ToolResult;
import com.sia.assistant.session.SessionService;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * screen.capture_region 의 도구 경계 — 네 좌표가 다 있어야 CaptureService 로 내려가고, 인자는 tool_call 기록에 그대로 남는다.
 * 사각형 정규화·잘라내기 규칙은 CaptureServiceTest 가 검증한다.
 */
class ScreenToolsTest {

    private ToolCallRecorder recorder;
    private CaptureService captureService;
    private ScreenTools tools;

    @BeforeEach
    void setUp() {
        SessionService sessionService = mock(SessionService.class);
        when(sessionService.requireActive()).thenReturn(5L);
        recorder = mock(ToolCallRecorder.class);
        captureService = mock(CaptureService.class);
        // McpResults 는 @McpTool 메서드(전송 표현)만 쓴다 — ...Result 경로에는 필요 없다
        tools = new ScreenTools(new ToolGate(sessionService, recorder), mock(RefResolver.class), captureService, null);
    }

    @Test
    @DisplayName("네 좌표는 그대로 CaptureService.captureRegion 에 넘어가고 그 반환값이 도구 결과가 된다")
    void delegatesRegionCapture() {
        Map<String, Object> saved = Map.of("path", "C:\\Users\\me\\Pictures\\SIA\\capture_20260902_041230.png",
                "url", "/api/captures/capture_20260902_041230.png", "width", 4, "height", 3);
        when(captureService.captureRegion(6, 1, 2, 4)).thenReturn(saved);

        ToolResult result = tools.captureRegionResult(6, 1, 2, 4);

        assertThat(result.ok()).isTrue();
        assertThat(result.data()).isEqualTo(saved);
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("x1", 6);
        args.put("y1", 1);
        args.put("x2", 2);
        args.put("y2", 4);
        verify(recorder).record(eq("screen.capture_region"), eq(args), eq(Caller.LLM),
                eq("EXECUTED"), isNull(), eq(5L), anyLong());
    }

    @Test
    @DisplayName("좌표가 하나라도 빠지면 INVALID_REQUEST 로 환원되고 캡처는 일어나지 않는다")
    void missingCoordinateFails() {
        ToolResult result = tools.captureRegionResult(6, 1, null, 4);

        assertThat(result.ok()).isFalse();
        // 인자 형식 오류다 — LLM 이 "재시도"가 아니라 "인자를 고쳐 다시 호출"로 읽어야 한다 (API 명세 §3.1)
        assertThat(result.code()).isEqualTo("INVALID_REQUEST");
        assertThat(result.message()).contains("x1, y1, x2, y2");
        verifyNoInteractions(captureService);
        // 정책 게이트가 막은 게 아니므로 기록의 outcome 은 그대로 FAILED 다
        verify(recorder).record(eq("screen.capture_region"), any(), eq(Caller.LLM),
                eq("FAILED"), any(), eq(5L), anyLong());
    }
}
