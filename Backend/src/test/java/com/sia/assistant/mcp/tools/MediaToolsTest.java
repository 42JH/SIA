package com.sia.assistant.mcp.tools;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyChar;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.sia.assistant.context.ContextService;
import com.sia.assistant.control.input.SendInputService;
import com.sia.assistant.control.window.WindowService;
import com.sia.assistant.logging.ToolCallRecorder;
import com.sia.assistant.mcp.Caller;
import com.sia.assistant.mcp.ToolGate;
import com.sia.assistant.mcp.ToolResult;
import com.sia.assistant.session.SessionService;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * media.seek 의 도구 경계 — 의미 방향(forward/backward)을 물리 방향키(right/left)로 옮기고 횟수를 넘길 뿐이다.
 * 1~10 클램프와 확장 키 플래그는 SendInputService 의 몫이라 여기서는 위임과 거절만 본다.
 * ★ 나머지 media.* 와 달리 유튜브 분기가 없다는 것이 이 도구의 계약이다 — 아래 두 테스트가 그것을 잡는다.
 */
class MediaToolsTest {

    private ToolCallRecorder recorder;
    private ContextService contextService;
    private WindowService windowService;
    private SendInputService sendInput;
    private MediaTools tools;

    @BeforeEach
    void setUp() {
        SessionService sessionService = mock(SessionService.class);
        when(sessionService.requireActive()).thenReturn(5L);
        recorder = mock(ToolCallRecorder.class);
        contextService = mock(ContextService.class);
        windowService = mock(WindowService.class);
        sendInput = mock(SendInputService.class);
        // McpResults 는 @McpTool 메서드(전송 표현)만 쓴다 — ...Result 경로에는 필요 없다
        tools = new MediaTools(new ToolGate(sessionService, recorder), contextService, windowService,
                sendInput, null);
    }

    @Test
    @DisplayName("forward 는 오른쪽 방향키 한 번 — amount 를 생략하면 1이다")
    void forwardTapsRightArrowOnce() {
        ToolResult result = tools.seekResult("forward", null);

        assertThat(result.ok()).isTrue();
        verify(sendInput).arrowKey("right", 1);
        verify(recorder).record(eq("media.seek"), eq(Map.of("dir", "forward")), eq(Caller.LLM),
                eq("EXECUTED"), isNull(), eq(5L), anyLong());
    }

    @Test
    @DisplayName("backward 는 왼쪽 방향키를 amount 만큼 누른다")
    void backwardTapsLeftArrowAmountTimes() {
        ToolResult result = tools.seekResult("backward", 5);

        assertThat(result.ok()).isTrue();
        verify(sendInput).arrowKey("left", 5);
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("dir", "backward");
        args.put("amount", 5);
        verify(recorder).record(eq("media.seek"), eq(args), eq(Caller.LLM),
                eq("EXECUTED"), isNull(), eq(5L), anyLong());
    }

    @Test
    @DisplayName("포그라운드가 유튜브여도 방향키다 — 탐색에는 시스템 미디어 키 폴백이 없어 분기 자체를 두지 않는다")
    void youtubeForegroundStillUsesArrowKey() {
        when(windowService.foregroundHwnd()).thenReturn(77L);
        when(contextService.isYoutube(77L)).thenReturn(true);

        ToolResult result = tools.seekResult("forward", 2);

        assertThat(result.ok()).isTrue();
        verify(sendInput).arrowKey("right", 2);
        // 유튜브 단축키도, 창 포커스도 타지 않는다 — 제목 오판이 이 도구를 흔들지 못한다
        verify(sendInput, never()).key(anyChar());
        verify(windowService, never()).focus(anyLong());
    }

    @Test
    @DisplayName("모르는 방향은 INVALID_REQUEST — 합성 입력은 나가지 않는다")
    void unknownDirectionFails() {
        ToolResult result = tools.seekResult("rewind", 3);

        assertThat(result.ok()).isFalse();
        // 인자 형식 오류다 — LLM 이 "재시도"가 아니라 "인자를 고쳐 다시 호출"로 읽어야 한다 (API 명세 §3.1)
        assertThat(result.code()).isEqualTo("INVALID_REQUEST");
        assertThat(result.message()).contains("forward|backward");
        verify(sendInput, never()).arrowKey(anyString(), anyInt());
        verifyNoInteractions(contextService, windowService);
        verify(recorder).record(eq("media.seek"), any(), eq(Caller.LLM),
                eq("FAILED"), any(), eq(5L), anyLong());
    }

    @Test
    @DisplayName("media.play_pause 는 그대로 유튜브 분기다 — seek 이 분기를 벗어나도 나머지는 그대로다")
    void playPauseStillBranchesOnYoutube() {
        when(windowService.foregroundHwnd()).thenReturn(77L);
        when(contextService.isYoutube(77L)).thenReturn(true);

        ToolResult result = tools.playPauseResult();

        assertThat(result.ok()).isTrue();
        assertThat(result.data()).isEqualTo(Map.of("via", "youtube"));
        verify(windowService).focus(77L);
        verify(sendInput).key('k');
    }
}
