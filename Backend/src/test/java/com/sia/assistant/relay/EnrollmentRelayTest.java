package com.sia.assistant.relay;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

/**
 * command_rejected — 명령 문장 낭독 실패 사유 중계 (프로토콜 §8.7).
 * 거절은 상태를 진행시키지 않는다: 문장을 재발급하지 않아야 AI 가 기다리는 n 과 어긋나지 않는다.
 */
class EnrollmentRelayTest {

    private final ObjectMapper om = new ObjectMapper();
    private AgentHub agentHub;
    private FeHub feHub;
    private EnrollmentRelay relay;

    @BeforeEach
    void setUp() {
        agentHub = mock(AgentHub.class);
        feHub = mock(FeHub.class);
        relay = new EnrollmentRelay(agentHub, feHub);
    }

    @Test
    @DisplayName("command_rejected 는 n·total·reason 과 함께 code 를 그대로 실어 FE 로 간다")
    void rejectedCarriesCodeWhenPresent() {
        relay.onCommandRejected(om.readTree(
                "{\"n\":2,\"reason\":\"너무 짧게 들렸어요.\",\"code\":\"TOO_SHORT\"}"));

        verify(feHub).send(eq("command_rejected"), argThat(body ->
                body instanceof Map<?, ?> m
                        && Integer.valueOf(2).equals(m.get("n"))
                        && Integer.valueOf(5).equals(m.get("total"))
                        && "너무 짧게 들렸어요.".equals(m.get("reason"))
                        && "TOO_SHORT".equals(m.get("code"))));
    }

    @Test
    @DisplayName("code 가 없으면 키 자체를 넣지 않는다 — FE 는 reason 으로 폴백한다")
    void rejectedOmitsCodeWhenAbsent() {
        relay.onCommandRejected(om.readTree("{\"n\":1,\"reason\":\"너무 짧게 들렸어요.\"}"));

        verify(feHub).send(eq("command_rejected"), argThat(body ->
                body instanceof Map<?, ?> m && !m.containsKey("code")));
    }

    @Test
    @DisplayName("거절은 문장을 재발급하지 않는다 — AI 가 같은 n 을 계속 기다린다")
    void rejectedDoesNotReissueSentence() {
        relay.onCommandRejected(om.readTree("{\"n\":3,\"reason\":\"너무 짧게 들렸어요.\"}"));

        verify(feHub, never()).send(eq("command_sentence"), any());
        verifyNoInteractions(agentHub);
    }

    @Test
    @DisplayName("command_progress 는 종전대로 다음 문장을 발급한다 — 거절 추가가 진행 경로를 바꾸지 않는다")
    void progressStillAdvances() {
        relay.onCommandProgress(om.readTree("{\"n\":3}"));

        verify(feHub).send(eq("command_progress"), eq(Map.of("n", 3, "total", 5)));
        verify(feHub).send(eq("command_sentence"), eq(Map.of("n", 4, "total", 5)));
        verify(agentHub).send(eq("command_collect"), eq(Map.of("n", 4)));
    }
}
