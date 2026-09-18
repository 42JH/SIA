package com.sia.assistant.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.any;
import static org.mockito.Mockito.anyLong;
import static org.mockito.Mockito.eq;
import static org.mockito.Mockito.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.logging.ToolCallRecorder;
import com.sia.assistant.session.SessionService;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class ToolGateTest {

    private SessionService sessionService;
    private ToolCallRecorder recorder;
    private ToolGate gate;

    @BeforeEach
    void setUp() {
        sessionService = mock(SessionService.class);
        recorder = mock(ToolCallRecorder.class);
        gate = new ToolGate(sessionService, recorder);
    }

    @Test
    @DisplayName("카탈로그에 없는 도구는 실행도 기록도 없이 failed 다")
    void unknownToolFailsWithoutRecording() {
        AtomicBoolean executed = new AtomicBoolean();

        ToolResult result = gate.run("no.such.tool", Map.of(), Caller.LLM, () -> {
            executed.set(true);
            return null;
        });

        assertThat(result.ok()).isFalse();
        assertThat(result.code()).isEqualTo("FAILED");
        assertThat(executed).isFalse();
        verifyNoInteractions(recorder);
    }

    @Test
    @DisplayName("세션 불필요(S=false) 도구는 세션이 없어도 실행되고 EXECUTED 로 기록된다")
    void sessionFreeToolRunsWithoutSession() {
        when(sessionService.activeOrNull()).thenReturn(null);

        ToolResult result = gate.run("context.get", null, Caller.LLM, () -> "ctx");

        assertThat(result.ok()).isTrue();
        assertThat(result.data()).isEqualTo("ctx");
        // null args 는 빈 맵으로 안전화되어 기록된다
        verify(recorder).record(eq("context.get"), eq(Map.of()), eq(Caller.LLM),
                eq("EXECUTED"), isNull(), isNull(), anyLong());
    }

    @Test
    @DisplayName("세션 필요(S=true) 도구는 세션이 없으면 BLOCKED 로 환원된다")
    void sessionRequiredToolIsBlockedWithoutSession() {
        when(sessionService.requireActive())
                .thenThrow(new BlockedException(ErrorCode.SESSION_REQUIRED, "세션이 활성화되지 않았습니다"));
        AtomicBoolean executed = new AtomicBoolean();

        ToolResult result = gate.run("window.focus", Map.of("winRef", "win:1"), Caller.LLM, () -> {
            executed.set(true);
            return null;
        });

        assertThat(result.ok()).isFalse();
        assertThat(result.code()).isEqualTo("SESSION_REQUIRED");
        assertThat(executed).isFalse();
        verify(recorder).record(eq("window.focus"), any(), eq(Caller.LLM),
                eq("BLOCKED"), eq("세션이 활성화되지 않았습니다"), isNull(), anyLong());
    }

    @Test
    @DisplayName("C 도구도 BE 는 보류하지 않고 바로 실행한다 — 동의는 AI 가 호출 전에 받는다")
    void confirmToolRunsImmediately() {
        when(sessionService.requireActive()).thenReturn(5L);
        Map<String, Object> args = Map.of("winRef", "win:1");
        AtomicBoolean executed = new AtomicBoolean();

        ToolResult result = gate.run("window.close", args, Caller.LLM, () -> {
            executed.set(true);
            return "closed";
        });

        assertThat(result.ok()).isTrue();
        assertThat(result.data()).isEqualTo("closed");
        assertThat(executed).isTrue();
        verify(recorder).record(eq("window.close"), eq(args), eq(Caller.LLM),
                eq("EXECUTED"), isNull(), eq(5L), anyLong());
    }

    @Test
    @DisplayName("action 이 던진 BlockedException 은 코드 그대로 BLOCKED 결과가 된다")
    void blockedActionBecomesBlockedResult() {
        when(sessionService.requireActive()).thenReturn(5L);

        ToolResult result = gate.run("window.focus", Map.of(), Caller.LLM, () -> {
            throw new BlockedException(ErrorCode.ELEVATED_WINDOW, "관리자 권한으로 실행된 창은 제어할 수 없습니다");
        });

        assertThat(result.ok()).isFalse();
        assertThat(result.code()).isEqualTo("ELEVATED_WINDOW");
        verify(recorder).record(eq("window.focus"), any(), eq(Caller.LLM),
                eq("BLOCKED"), any(), eq(5L), anyLong());
    }

    @Test
    @DisplayName("ApiException 의 사용자 메시지는 failed 결과에 그대로 실린다")
    void apiExceptionKeepsUserMessage() {
        when(sessionService.activeOrNull()).thenReturn(null);

        ToolResult result = gate.run("context.get", Map.of(), Caller.LLM, () -> {
            throw new ApiException(ErrorCode.APP_PATH_INVALID, "경로가 잘못되었습니다");
        });

        assertThat(result.ok()).isFalse();
        assertThat(result.code()).isEqualTo("FAILED");
        assertThat(result.message()).isEqualTo("경로가 잘못되었습니다");
    }

    @Test
    @DisplayName("인자 형식 오류는 INVALID_REQUEST 코드로 나가되 outcome 은 FAILED 로 기록된다")
    void invalidRequestKeepsItsCodeButRecordsFailed() {
        when(sessionService.activeOrNull()).thenReturn(null);

        ToolResult result = gate.run("context.get", Map.of(), Caller.LLM, () -> {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "포그라운드 창이 없습니다");
        });

        assertThat(result.ok()).isFalse();
        assertThat(result.code()).isEqualTo("INVALID_REQUEST");
        assertThat(result.message()).isEqualTo("포그라운드 창이 없습니다");
        // 정책 게이트가 막은 게 아니다 — tool_call.outcome 의 CHECK 제약도 세 값뿐이다
        verify(recorder).record(eq("context.get"), any(), eq(Caller.LLM),
                eq("FAILED"), any(), isNull(), anyLong());
    }

    @Test
    @DisplayName("일반 예외는 일반 문구로 감추고 원인은 기록에만 남긴다")
    void genericExceptionIsMaskedButRecorded() {
        when(sessionService.activeOrNull()).thenReturn(null);

        ToolResult result = gate.run("context.get", Map.of(), Caller.LLM, () -> {
            throw new IllegalStateException("boom");
        });

        assertThat(result.ok()).isFalse();
        assertThat(result.message()).isEqualTo("도구 실행에 실패했습니다");
        verify(recorder).record(eq("context.get"), any(), eq(Caller.LLM),
                eq("FAILED"), eq("boom"), isNull(), anyLong());
    }

    @Test
    @DisplayName("ApiException 의 detail 은 콘솔에만 붙는다 — 사용자 문장과 기록은 그대로다")
    void detailReachesTheConsoleOnly() {
        ch.qos.logback.classic.Logger logger =
                (ch.qos.logback.classic.Logger) org.slf4j.LoggerFactory.getLogger(ToolGate.class);
        ch.qos.logback.core.read.ListAppender<ch.qos.logback.classic.spi.ILoggingEvent> logs =
                new ch.qos.logback.core.read.ListAppender<>();
        logs.start();
        logger.addAppender(logs);
        try {
            when(sessionService.activeOrNull()).thenReturn(null);

            ToolResult result = gate.run("context.get", Map.of(), Caller.GESTURE, () -> {
                throw new ApiException(ErrorCode.INTERNAL_ERROR, "파일을 열지 못했습니다. 잠시 후 다시 시도해주세요",
                        "java.io.IOException: Failed to open PikaPet.exe. Error message: 액세스가 거부되었습니다");
            });

            // 사용자에게 나가는 문장은 그대로다 — 윈도우 에러가 FE 화면으로 새면 안 된다
            assertThat(result.message()).isEqualTo("파일을 열지 못했습니다. 잠시 후 다시 시도해주세요");
            verify(recorder).record(eq("context.get"), any(), eq(Caller.GESTURE),
                    eq("FAILED"), eq("파일을 열지 못했습니다. 잠시 후 다시 시도해주세요"), isNull(), anyLong());
            // 진짜 사유는 콘솔에만 — 이게 없으면 QA 로그에 한 문장만 남아 진단이 불가능하다
            assertThat(logs.list).singleElement()
                    .extracting(e -> e.getFormattedMessage()).asString()
                    .contains(" -> FAILED 파일을 열지 못했습니다. 잠시 후 다시 시도해주세요"
                            + " | java.io.IOException: Failed to open PikaPet.exe."
                            + " Error message: 액세스가 거부되었습니다 (");
        } finally {
            logger.detachAppender(logs);
        }
    }

    @Test
    @DisplayName("도구 실행 한 건마다 이름·caller·인자·결과가 콘솔 INFO 한 줄로 남는다")
    void everyRunLeavesOneConsoleLine() {
        ch.qos.logback.classic.Logger logger =
                (ch.qos.logback.classic.Logger) org.slf4j.LoggerFactory.getLogger(ToolGate.class);
        ch.qos.logback.core.read.ListAppender<ch.qos.logback.classic.spi.ILoggingEvent> logs =
                new ch.qos.logback.core.read.ListAppender<>();
        logs.start();
        logger.addAppender(logs);
        try {
            when(sessionService.activeOrNull()).thenReturn(null);
            when(sessionService.requireActive())
                    .thenThrow(new BlockedException(ErrorCode.SESSION_REQUIRED, "세션 없음"));

            gate.run("context.get", Map.of(), Caller.GESTURE, () -> "ctx");
            gate.run("window.focus", Map.of("winRef", "win:1"), Caller.LLM, () -> null);
            gate.run("context.get", Map.of(), Caller.LLM, () -> {
                throw new IllegalStateException("boom");
            });
            gate.run("no.such.tool", Map.of(), Caller.LLM, () -> null);

            assertThat(logs.list).extracting(e -> e.getFormattedMessage())
                    .satisfiesExactly(
                            m -> assertThat(m).startsWith("[tool] context.get caller=GESTURE args={} -> EXECUTED ("),
                            m -> assertThat(m).startsWith(
                                    "[tool] window.focus caller=LLM args={winRef=win:1} -> BLOCKED SESSION_REQUIRED ("),
                            m -> assertThat(m).startsWith("[tool] context.get caller=LLM args={} -> FAILED boom ("),
                            m -> assertThat(m).isEqualTo("[tool] no.such.tool caller=LLM args={} -> UNKNOWN"));
        } finally {
            logger.detachAppender(logs);
        }
    }
}
