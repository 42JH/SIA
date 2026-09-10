package com.sia.assistant.mcp.tools;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyLong;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.sia.assistant.control.audio.AudioService;
import com.sia.assistant.control.input.SendInputService;
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
 * volume.set 의 도구 경계 — level 은 그대로 AudioService 로 내려가고, 결과는 <b>실제 반영된 값</b>이다.
 * 0~100 잘라내기와 음소거 해제는 AudioService 의 몫이라 여기서는 위임과 환원만 본다.
 */
class VolumeToolsTest {

    private ToolCallRecorder recorder;
    private AudioService audio;
    private SendInputService sendInput;
    private VolumeTools tools;

    @BeforeEach
    void setUp() {
        SessionService sessionService = mock(SessionService.class);
        when(sessionService.requireActive()).thenReturn(5L);
        recorder = mock(ToolCallRecorder.class);
        audio = mock(AudioService.class);
        sendInput = mock(SendInputService.class);
        // McpResults 는 @McpTool 메서드(전송 표현)만 쓴다 — ...Result 경로에는 필요 없다
        tools = new VolumeTools(new ToolGate(sessionService, recorder), sendInput, audio, null);
    }

    @Test
    @DisplayName("level 은 AudioService 로 넘어가고, 도구 결과는 실제 반영된 level·muted 다")
    void delegatesSet() {
        when(audio.set(30)).thenReturn(new AudioService.Volume(30, false));

        ToolResult result = tools.setResult(30);

        assertThat(result.ok()).isTrue();
        Map<String, Object> expected = new LinkedHashMap<>();
        expected.put("level", 30);
        expected.put("muted", false);
        assertThat(result.data()).isEqualTo(expected);
        verify(audio).set(30);
        verify(recorder).record(eq("volume.set"), eq(Map.of("level", 30)), eq(Caller.LLM),
                eq("EXECUTED"), isNull(), eq(5L), anyLong());
    }

    @Test
    @DisplayName("잘려서 반영된 값은 요청 값이 아니라 반영된 값으로 돌아온다 — LLM 이 그대로 사용자에게 읽는다")
    void reportsAppliedLevelNotRequested() {
        when(audio.set(150)).thenReturn(new AudioService.Volume(100, false));

        ToolResult result = tools.setResult(150);

        assertThat(result.ok()).isTrue();
        assertThat(((Map<?, ?>) result.data()).get("level")).isEqualTo(100);
    }

    @Test
    @DisplayName("level 이 빠지면 INVALID_REQUEST 로 환원되고 볼륨은 건드리지 않는다")
    void missingLevelFails() {
        ToolResult result = tools.setResult(null);

        assertThat(result.ok()).isFalse();
        // 인자 형식 오류다 — LLM 이 "재시도"가 아니라 "인자를 고쳐 다시 호출"로 읽어야 한다 (API 명세 §3.1)
        assertThat(result.code()).isEqualTo("INVALID_REQUEST");
        assertThat(result.message()).contains("0~100");
        verifyNoInteractions(audio);
        verify(recorder).record(eq("volume.set"), any(), eq(Caller.LLM),
                eq("FAILED"), any(), eq(5L), anyLong());
    }

    @Test
    @DisplayName("volume.step 은 그대로 미디어 키 경로다 — 절대값 도구가 생겨도 단계 조절은 COM 을 타지 않는다")
    void stepStillUsesMediaKey() {
        ToolResult result = tools.stepResult("up");

        assertThat(result.ok()).isTrue();
        verify(sendInput).mediaKey("VOL_UP");
        verifyNoInteractions(audio);
    }

    @Test
    @DisplayName("모르는 방향은 INVALID_REQUEST — 합성 입력은 나가지 않는다")
    void unknownDirectionFails() {
        ToolResult result = tools.stepResult("sideways");

        assertThat(result.ok()).isFalse();
        assertThat(result.code()).isEqualTo("INVALID_REQUEST");
        verify(sendInput, org.mockito.Mockito.never()).mediaKey(any());
        verify(audio, org.mockito.Mockito.never()).set(anyInt());
    }
}
