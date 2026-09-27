package com.sia.assistant.gestureexec;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.sia.assistant.context.ContextService;
import com.sia.assistant.mcp.Caller;
import com.sia.assistant.mcp.ToolInvoker;
import com.sia.assistant.mcp.ToolResult;
import com.sia.assistant.session.SessionService;
import com.sia.assistant.settings.GestureService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.mockito.InOrder;
import tools.jackson.databind.ObjectMapper;

/**
 * 제스처 매크로 실행 규칙. 핵심은 세션 게이트가 <b>매크로 단위</b>라는 것 —
 * S 도구가 하나라도 있으면 첫 스텝 전에 막아 반쯤 실행된 매크로를 남기지 않는다 (프로토콜 §8.6).
 */
class GestureExecutorTest {

    private static final long TIMEOUT_MS = 2000;

    private GestureService gestureService;
    private ContextService contextService;
    private ToolInvoker toolInvoker;
    private SessionService sessionService;
    private AgentHub agentHub;
    private FeHub feHub;
    private GestureExecutor executor;

    @BeforeEach
    void setUp() {
        gestureService = mock(GestureService.class);
        contextService = mock(ContextService.class);
        toolInvoker = mock(ToolInvoker.class);
        sessionService = mock(SessionService.class);
        agentHub = mock(AgentHub.class);
        feHub = mock(FeHub.class);
        executor = new GestureExecutor(gestureService, contextService, toolInvoker, sessionService,
                agentHub, feHub);
        when(contextService.chainFor(any())).thenReturn(List.of());
    }

    @Test
    @DisplayName("세션이 없으면 S 도구가 든 매크로는 첫 스텝도 실행하지 않는다 — 게이트는 매크로 단위다")
    void macroWithSessionToolIsBlockedBeforeAnyStep() {
        // volume.step(S) 앞에 context.get(비 S) 을 둔다 — 스텝 단위 게이트였다면 앞 스텝이 이미 실행됐을 자리다
        stubGesture("볼륨 업", step("context.get"), step("volume.step"));
        when(sessionService.activeOrNull()).thenReturn(null);

        executor.execute(exec("볼륨 업"));

        Map<String, Object> body = awaitResult();
        assertThat(body).containsEntry("ok", false).containsEntry("message", "세션이 활성화되지 않았습니다");
        assertThat(body.get("steps")).asList().isEmpty();
        verify(toolInvoker, never()).invoke(any(), any(), any());
    }

    @Test
    @DisplayName("S 도구가 없는 매크로는 세션이 없어도 그대로 실행된다")
    void macroWithoutSessionToolRunsWithoutSession() {
        stubGesture("창 목록", step("context.get"));
        when(sessionService.activeOrNull()).thenReturn(null);
        when(toolInvoker.invoke(eq("context.get"), any(), eq(Caller.GESTURE)))
                .thenReturn(ToolResult.ok(Map.of("windows", List.of())));

        executor.execute(exec("창 목록"));

        Map<String, Object> body = awaitResult();
        assertThat(body).containsEntry("ok", true);
        verify(toolInvoker).invoke(eq("context.get"), any(), eq(Caller.GESTURE));
    }

    @Test
    @DisplayName("세션이 있으면 S 도구 매크로는 스텝 순서대로 실행된다")
    void macroRunsWhenSessionIsActive() {
        stubGesture("볼륨 업", step("volume.step"));
        when(sessionService.activeOrNull()).thenReturn(new SessionService.Active(7L, "2026-09-03 00:00:00.000", 0L));
        when(toolInvoker.invoke(eq("volume.step"), any(), eq(Caller.GESTURE)))
                .thenReturn(ToolResult.ok(null));

        executor.execute(exec("볼륨 업"));

        Map<String, Object> body = awaitResult();
        assertThat(body).containsEntry("ok", true);
        assertThat(body.get("steps")).asList().hasSize(1);
    }

    @Test
    @DisplayName("활성 세션이면 첫 스텝 전에 세션을 갱신한다 — 제스처를 쓰는 동안 세션이 끊기지 않는다")
    void activeSessionIsRenewedBeforeFirstStep() {
        stubGesture("볼륨 업", step("volume.step"));
        when(sessionService.activeOrNull()).thenReturn(new SessionService.Active(7L, "2026-09-03 00:00:00.000", 0L));
        when(toolInvoker.invoke(eq("volume.step"), any(), eq(Caller.GESTURE)))
                .thenReturn(ToolResult.ok(null));

        executor.execute(exec("볼륨 업"));

        assertThat(awaitResult()).containsEntry("ok", true);
        InOrder order = inOrder(sessionService, toolInvoker);
        order.verify(sessionService).renew(null);
        order.verify(toolInvoker).invoke(eq("volume.step"), any(), eq(Caller.GESTURE));
    }

    @Test
    @DisplayName("세션 없이 도는 비 S 매크로는 갱신하지 않는다 — renew 는 활성 세션이 없으면 던진다")
    void macroWithoutSessionIsNotRenewed() {
        stubGesture("창 목록", step("context.get"));
        when(sessionService.activeOrNull()).thenReturn(null);
        when(toolInvoker.invoke(eq("context.get"), any(), eq(Caller.GESTURE)))
                .thenReturn(ToolResult.ok(Map.of("windows", List.of())));

        executor.execute(exec("창 목록"));

        assertThat(awaitResult()).containsEntry("ok", true);
        verify(sessionService, never()).renew(any());
    }

    @Test
    @DisplayName("세션 게이트에 막힌 매크로는 세션을 갱신하지 않는다")
    void blockedMacroIsNotRenewed() {
        stubGesture("볼륨 업", step("volume.step"));
        when(sessionService.activeOrNull()).thenReturn(null);

        executor.execute(exec("볼륨 업"));

        assertThat(awaitResult()).containsEntry("ok", false);
        verify(sessionService, never()).renew(any());
    }

    @Test
    @DisplayName("기능이 지정되지 않은 제스처는 세션을 갱신하지 않는다 — 갱신은 유효 판정 뒤다")
    void unassignedGestureIsNotRenewed() {
        stubGesture("손바닥 펴기");
        when(sessionService.activeOrNull()).thenReturn(new SessionService.Active(7L, "2026-09-03 00:00:00.000", 0L));

        executor.execute(exec("손바닥 펴기"));

        assertThat(awaitResult()).containsEntry("ok", false);
        verify(sessionService, never()).renew(any());
    }

    @Test
    @DisplayName("스텝이 인자 형식 오류로 실패하면 outcome 은 BLOCKED 가 아니라 FAILED 다")
    void invalidRequestStepIsReportedAsFailed() {
        stubGesture("스크롤", step("scroll.step"));
        when(sessionService.activeOrNull()).thenReturn(new SessionService.Active(7L, "2026-09-03 00:00:00.000", 0L));
        when(toolInvoker.invoke(eq("scroll.step"), any(), eq(Caller.GESTURE)))
                .thenReturn(ToolResult.invalid("지원하지 않는 스크롤 방향입니다"));

        executor.execute(exec("스크롤"));

        Map<String, Object> body = awaitResult();
        assertThat(body).containsEntry("ok", false);
        @SuppressWarnings("unchecked")
        List<Map<String, Object>> steps = (List<Map<String, Object>>) body.get("steps");
        assertThat(steps.get(0)).containsEntry("outcome", "FAILED")
                .containsEntry("message", "지원하지 않는 스크롤 방향입니다");
    }

    @Test
    @DisplayName("기능이 지정되지 않은 제스처는 성공이 아니라 실패로 보고한다 — 빈 매크로는 실행이 아니다")
    void unassignedGestureIsReportedAsFailure() {
        stubGesture("손바닥 펴기"); // 기본 제공 제스처는 스텝 0개로 태어난다

        executor.execute(exec("손바닥 펴기"));

        Map<String, Object> body = awaitResult();
        assertThat(body).containsEntry("ok", false);
        assertThat((String) body.get("message")).contains("기능이 지정되지 않은");
        assertThat(body.get("steps")).asList().isEmpty();
        verify(toolInvoker, never()).invoke(any(), any(), any());
    }

    // ------------------------------------------------------------------ 도우미

    private void stubGesture(String name, GestureService.Step... steps) {
        GestureService.GestureDef def = new GestureService.GestureDef(
                1L, "HAND", null, name, name, false, true, true, List.of(steps));
        when(gestureService.find(eq(name), any())).thenReturn(Optional.of(def));
    }

    private static GestureService.Step step(String tool) {
        return new GestureService.Step(tool, Map.of(), null);
    }

    private static tools.jackson.databind.JsonNode exec(String name) {
        return new ObjectMapper().createObjectNode().put("name", name);
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> awaitResult() {
        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(agentHub, timeout(TIMEOUT_MS)).send(eq("gesture_result"), captor.capture());
        verify(feHub, timeout(TIMEOUT_MS)).send(eq("gesture_result"), any());
        return captor.getValue();
    }
}
