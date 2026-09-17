package com.sia.assistant.relay;

import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * 이름 불러보기(호출어 샘플) 중계 — BE 는 세지 않고 그대로 넘긴다 (프로토콜 §8.7).
 * 샘플 수의 원천은 AI 라서 BE 가 total 을 고쳐 쓰면 FE 진행바가 AI 와 어긋난다.
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
    @DisplayName("시작은 AI 에 wakeword_enroll_start 만 보낸다 — FE 로는 아무것도 가지 않는다")
    void startGoesToAgentOnly() {
        relay.startWakeword();

        verify(agentHub).send(eq("wakeword_enroll_start"), eq(Map.of()));
        verifyNoInteractions(feHub);
    }

    @Test
    @DisplayName("wakeword_sample 은 n·total 을 그대로 wakeword_progress 로 넘긴다")
    void samplePassesPayloadThrough() {
        JsonNode d = om.readTree("{\"n\":3,\"total\":5}");
        relay.onWakewordSample(d);

        verify(feHub).send(eq("wakeword_progress"), argThat(body ->
                body instanceof JsonNode j && j.path("n").asInt() == 3 && j.path("total").asInt() == 5));
        verifyNoInteractions(agentHub);
    }

    @Test
    @DisplayName("wakeword_done 은 빈 본문으로 FE 에 간다")
    void doneRelayed() {
        relay.onWakewordDone();

        verify(feHub).send(eq("wakeword_done"), eq(Map.of()));
        verifyNoInteractions(agentHub);
    }

    @Test
    @DisplayName("wakeword_rejected 는 n·total·reason·code 를 그대로 넘긴다 — 순번도 total 도 AI 가 쥔다")
    void rejectionPassesPayloadThrough() {
        JsonNode d = om.readTree(
                "{\"n\":3,\"total\":5,\"reason\":\"주변이 시끄러워요.\",\"code\":\"NOISY\"}");
        relay.onWakewordRejected(d);

        verify(feHub).send(eq("wakeword_rejected"), argThat(body ->
                body instanceof JsonNode j && j.path("n").asInt() == 3 && j.path("total").asInt() == 5
                        && "주변이 시끄러워요.".equals(j.path("reason").asText())
                        && "NOISY".equals(j.path("code").asText())));
        verifyNoInteractions(agentHub);
    }

    @Test
    @DisplayName("거절 본문이 객체가 아니면 빈 객체로 방어한다")
    void nonObjectRejectionFallsBackToEmpty() {
        relay.onWakewordRejected(om.readTree("[1,2]"));

        verify(feHub).send(eq("wakeword_rejected"), eq(Map.of()));
    }

}
