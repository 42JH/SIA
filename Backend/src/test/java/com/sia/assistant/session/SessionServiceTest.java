package com.sia.assistant.session;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.any;
import static org.mockito.Mockito.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.settings.SettingsService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

class SessionServiceTest {

    private JdbcTemplate jdbc;
    private FeHub feHub;
    private AgentHub agentHub;
    private SessionService service;

    @BeforeEach
    void setUp() {
        jdbc = mock(JdbcTemplate.class);
        PlatformTransactionManager txManager = mock(PlatformTransactionManager.class);
        when(txManager.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        SettingsService settingsService = mock(SettingsService.class);
        when(settingsService.peekSessionSeconds()).thenReturn(90);
        when(jdbc.queryForObject("SELECT last_insert_rowid()", Long.class)).thenReturn(7L);
        feHub = mock(FeHub.class);
        agentHub = mock(AgentHub.class);
        service = new SessionService(jdbc, txManager, settingsService, feHub, agentHub);
    }

    @AfterEach
    void tearDown() {
        service.shutdown();
    }

    @Test
    @DisplayName("세션 트리거는 WAKEWORD·UI 만 허용된다")
    void openRejectsUnknownTrigger() {
        assertThatThrownBy(() -> service.open("GESTURE"))
                .isInstanceOfSatisfying(ApiException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.INVALID_REQUEST));
    }

    @Test
    @DisplayName("open 은 ACTIVE 상태를 만들고 FE·에이전트 양쪽에 통지한다")
    void openActivatesAndPushes() {
        Map<String, Object> payload = service.open("WAKEWORD");

        assertThat(payload)
                .containsEntry("state", "ACTIVE")
                .containsEntry("sessionId", 7L)
                .containsEntry("remainingSec", 90);
        assertThat(service.requireActive()).isEqualTo(7L);
        assertThat(service.remainingSec()).isBetween(1, 90);
        verify(feHub).send(eq("session_state"), eq(payload));
        verify(agentHub).send(eq("session_state"), eq(payload));
    }

    @Test
    @DisplayName("활성 세션이 남은 채 다시 open 하면 이전 세션은 WATCHDOG 으로 닫힌다")
    void reopenClosesPreviousAsWatchdog() {
        service.open("WAKEWORD");
        service.open("UI");

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(feHub, times(3)).send(eq("session_state"), captor.capture());
        List<Map<String, Object>> sent = captor.getAllValues();
        assertThat(sent.get(0)).containsEntry("state", "ACTIVE");
        assertThat(sent.get(1)).containsEntry("state", "PASSIVE").containsEntry("reason", "WATCHDOG");
        assertThat(sent.get(2)).containsEntry("state", "ACTIVE");
    }

    @Test
    @DisplayName("호출어 개시는 세션이 없을 때만 연다 — 시작 시각은 BE 가 이벤트를 받은 순간이다")
    void wakewordOpensOnlyWhenIdle() {
        Map<String, Object> opened = service.openOnWakeword();

        assertThat(opened)
                .containsEntry("state", "ACTIVE")
                .containsEntry("sessionId", 7L);
        verify(feHub).send(eq("session_state"), eq(opened));
    }

    @Test
    @DisplayName("이미 활성이면 호출어 개시는 세션을 갈아엎지도, 연장하지도, 통지하지도 않는다")
    void wakewordOnActiveSessionIsSilent() {
        Map<String, Object> first = service.open("WAKEWORD");
        long deadlineBefore = (long) first.get("deadlineMs");
        clearInvocations(feHub, agentHub);

        Map<String, Object> again = service.openOnWakeword();

        // 같은 세션이 그대로다 — WATCHDOG 도, 새 id 도 없다
        assertThat(again).containsEntry("sessionId", 7L).containsEntry("state", "ACTIVE");
        // 갱신도 아니다: 마감시각이 밀리지 않는다 (오인식 호출어가 세션을 늘리면 안 된다)
        assertThat((long) again.get("deadlineMs")).isEqualTo(deadlineBefore);
        // 상태가 안 바뀌었으니 통지도 없다
        verifyNoInteractions(feHub, agentHub);
    }

    @Test
    @DisplayName("세션이 없으면 renew 는 SESSION_REQUIRED 다")
    void renewWithoutSessionIsBlocked() {
        assertThatThrownBy(() -> service.renew(null))
                .isInstanceOfSatisfying(BlockedException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.SESSION_REQUIRED));
    }

    @Test
    @DisplayName("이미 끝난(다른) 세션 id 로는 renew 할 수 없다")
    void renewWithStaleIdIsBlocked() {
        service.open("WAKEWORD");

        assertThatThrownBy(() -> service.renew(99L))
                .isInstanceOfSatisfying(BlockedException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.SESSION_REQUIRED));
    }

    @Test
    @DisplayName("renew 는 같은 세션 id 로 마감만 미룬다")
    void renewExtendsDeadline() {
        service.open("WAKEWORD");

        Map<String, Object> payload = service.renew(7L);

        assertThat(payload)
                .containsEntry("state", "ACTIVE")
                .containsEntry("sessionId", 7L)
                .containsEntry("remainingSec", 90);
        assertThat(service.requireActive()).isEqualTo(7L);
    }

    @Test
    @DisplayName("종료 사유는 네 가지 열거값만 허용된다")
    void endRejectsUnknownReason() {
        assertThatThrownBy(() -> service.end(7L, "BECAUSE"))
                .isInstanceOfSatisfying(ApiException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.INVALID_REQUEST));
        assertThatThrownBy(() -> service.end(7L, null))
                .isInstanceOf(ApiException.class);
    }

    @Test
    @DisplayName("end 는 PASSIVE 로 전환하고 이후 세션 필요 도구를 막는다")
    void endDeactivates() {
        service.open("WAKEWORD");

        Map<String, Object> payload = service.end(7L, "STOPPED");

        assertThat(payload).containsEntry("state", "PASSIVE").containsEntry("reason", "STOPPED");
        assertThat(service.activeOrNull()).isNull();
        assertThat(service.remainingSec()).isZero();
        assertThatThrownBy(service::requireActive).isInstanceOf(BlockedException.class);
    }

    @Test
    @DisplayName("활성이 아닌 낡은 세션 id 의 종료는 진행 중 세션을 건드리지 않는다")
    void endingStaleSessionKeepsActiveOne() {
        service.open("WAKEWORD");

        service.end(99L, "STOPPED");

        assertThat(service.requireActive()).isEqualTo(7L);
        // PASSIVE 오인 통지가 없어야 한다 — open 의 ACTIVE 1건이 전부
        verify(feHub, times(1)).send(eq("session_state"), any());
    }

    @Test
    @DisplayName("reset 은 DB 를 건드리지 않고 메모리 상태만 비운 뒤 PASSIVE 를 통지한다")
    void resetClearsMemoryState() {
        service.open("WAKEWORD");

        service.reset();

        assertThat(service.activeOrNull()).isNull();
        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(feHub, times(2)).send(eq("session_state"), captor.capture());
        assertThat(captor.getAllValues().get(1))
                .containsEntry("state", "PASSIVE")
                .containsEntry("reason", "STOPPED");
    }

    @Test
    @DisplayName("세션이 없으면 remainingSec 은 0 이다")
    void remainingSecIsZeroWithoutSession() {
        assertThat(service.remainingSec()).isZero();
    }
}
