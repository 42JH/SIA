package com.sia.assistant.logging;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.Mockito.any;
import static org.mockito.Mockito.anyString;
import static org.mockito.Mockito.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sia.assistant.mcp.Caller;
import com.sia.assistant.ws.FeHub;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

class ToolCallRecorderTest {

    // INSERT 바인딩 순서: sql, session_id, app_target_id, tool_name, ts, args_json, caller, outcome, reason, latency_ms
    private static final int IDX_SESSION_ID = 1;
    private static final int IDX_APP_TARGET_ID = 2;
    private static final int IDX_TS = 4;
    private static final int IDX_ARGS_JSON = 5;
    private static final int IDX_CALLER = 6;
    private static final int IDX_REASON = 8;

    private org.springframework.jdbc.core.JdbcTemplate jdbc;
    private FeHub feHub;
    private ToolCallRecorder recorder;
    private final AtomicReference<Object[]> captured = new AtomicReference<>();

    @BeforeEach
    void setUp() {
        jdbc = mock(org.springframework.jdbc.core.JdbcTemplate.class);
        feHub = mock(FeHub.class);
        recorder = new ToolCallRecorder(jdbc, new ObjectMapper(), feHub);
        when(jdbc.update(anyString(), any(Object[].class))).thenAnswer(inv -> {
            captured.set(inv.getArguments());
            return 1;
        });
    }

    @Test
    @DisplayName("기록 후 FE 에 tool_result 를 push 한다")
    void recordsAndPushesToolResult() {
        recorder.record("window.focus", Map.of("winRef", "win:1"), Caller.GESTURE,
                "EXECUTED", null, 7L, 12L);

        Object[] args = captured.get();
        assertThat(args[IDX_SESSION_ID]).isEqualTo(7L);
        assertThat(args[IDX_CALLER]).isEqualTo("GESTURE");
        // ts 는 Times 의 고정폭 23자 UTC 텍스트다
        assertThat((String) args[IDX_TS]).hasSize(23);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> body = ArgumentCaptor.forClass(Map.class);
        verify(feHub).send(eq("tool_result"), body.capture());
        assertThat(body.getValue())
                .containsEntry("tool", "window.focus")
                .containsEntry("outcome", "EXECUTED")
                .containsEntry("caller", "GESTURE")
                .containsEntry("latencyMs", 12L)
                .doesNotContainKey("message");
    }

    @Test
    @DisplayName("caller 가 null 이면 LLM 으로 기록된다")
    void nullCallerDefaultsToLlm() {
        recorder.record("context.get", Map.of(), null, "EXECUTED", null, null, 1L);

        assertThat(captured.get()[IDX_CALLER]).isEqualTo("LLM");
    }

    @Test
    @DisplayName("args_json 은 500자 이내의 유효한 JSON 으로 줄고, reason 은 255자에서 잘린다")
    void longValuesAreTruncated() throws Exception {
        String longText = "x".repeat(600);

        recorder.record("files.save", Map.of("content", longText), Caller.LLM,
                "FAILED", longText, null, 1L);

        // ★ args_json 은 JSON 컬럼이다 — 중간에서 자르면 파싱이 깨지므로 유효한 객체로 감싼다
        String argsJson = (String) captured.get()[IDX_ARGS_JSON];
        assertThat(argsJson.length()).isLessThanOrEqualTo(500);
        assertThat(new ObjectMapper().readTree(argsJson).get("_truncated").asInt()).isGreaterThan(500);

        // reason 은 사람이 읽는 평문이라 그냥 자른다
        assertThat((String) captured.get()[IDX_REASON]).hasSize(255);
    }

    @Test
    @DisplayName("500자 이내면 args_json 을 그대로 둔다")
    void shortArgsAreUntouched() {
        recorder.record("scroll.step", Map.of("dir", "up"), Caller.GESTURE, "EXECUTED", null, 1L, 1L);

        assertThat((String) captured.get()[IDX_ARGS_JSON]).isEqualTo("{\"dir\":\"up\"}");
    }

    @Test
    @DisplayName("app_target 힌트는 바로 다음 기록 1건에만 실린다")
    void appTargetHintIsConsumedOnce() {
        recorder.hintAppTarget(42L);
        recorder.record("app.launch", Map.of(), Caller.LLM, "EXECUTED", null, 7L, 1L);
        assertThat(captured.get()[IDX_APP_TARGET_ID]).isEqualTo(42L);

        recorder.record("app.launch", Map.of(), Caller.LLM, "EXECUTED", null, 7L, 1L);
        assertThat(captured.get()[IDX_APP_TARGET_ID]).isNull();
    }

    @Test
    @DisplayName("DB 기록이 실패해도 예외가 새지 않고 FE push 는 계속된다")
    void dbFailureDoesNotPropagate() {
        when(jdbc.update(anyString(), any(Object[].class))).thenThrow(new RuntimeException("db down"));

        assertThatCode(() -> recorder.record("context.get", Map.of(), Caller.LLM,
                "EXECUTED", null, null, 1L)).doesNotThrowAnyException();

        verify(feHub).send(eq("tool_result"), any());
    }

    @Test
    @DisplayName("reason 이 있으면 FE 본문에 message 로 실린다")
    void reasonBecomesMessage() {
        recorder.record("window.focus", Map.of(), Caller.LLM, "BLOCKED",
                "세션이 활성화되지 않았습니다", null, 1L);

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> body = ArgumentCaptor.forClass(Map.class);
        verify(feHub).send(eq("tool_result"), body.capture());
        assertThat(body.getValue()).containsEntry("message", "세션이 활성화되지 않았습니다");
    }
}
