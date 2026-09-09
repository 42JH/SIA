package com.sia.assistant.wsroutes;

import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sia.assistant.registration.CalibrationOrchestrator;
import com.sia.assistant.registration.RegistrationOrchestrator;
import com.sia.assistant.registration.VoiceRegistrationOrchestrator;
import com.sia.assistant.relay.EnrollmentRelay;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.WsEvents;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * user_choice — AI 가 notice(kind:"choices")로 띄운 후보 목록의 클릭 응답 중계.
 * AI↔FE 직접 채널이 없으므로 BE 가 무해석으로 AI 에 넘긴다 (PROTOCOL.md §0·§2).
 */
class FeWsRoutesTest {

    private final ObjectMapper om = new ObjectMapper();
    private AgentHub agentHub;
    private FeWsRoutes routes;

    @BeforeEach
    void setUp() {
        agentHub = mock(AgentHub.class);
        routes = new FeWsRoutes(agentHub, mock(RegistrationOrchestrator.class),
                mock(VoiceRegistrationOrchestrator.class), mock(CalibrationOrchestrator.class),
                mock(EnrollmentRelay.class));
    }

    @Test
    @DisplayName("user_choice 는 페이로드 그대로 AI 로 중계된다 — BE 는 해석하지 않는다")
    void userChoiceIsRelayedVerbatim() throws Exception {
        routes.on(new WsEvents.FeMessage("user_choice",
                om.readTree("{\"choiceId\":\"c-7f31\",\"n\":1}")));

        verify(agentHub).send(eq("user_choice"), argThat(d ->
                d instanceof com.fasterxml.jackson.databind.JsonNode node
                        && "c-7f31".equals(node.path("choiceId").asText())
                        && node.path("n").asInt() == 1));
    }

    @Test
    @DisplayName("user_choice 의 data 가 객체가 아니면 빈 객체로 방어한다")
    void nonObjectPayloadFallsBackToEmpty() throws Exception {
        routes.on(new WsEvents.FeMessage("user_choice", om.readTree("[1,2]")));

        verify(agentHub).send(eq("user_choice"), eq(Map.of()));
    }

    @Test
    @DisplayName("모르는 type 은 조용히 무시된다")
    void unknownTypeIsIgnored() throws Exception {
        routes.on(new WsEvents.FeMessage("no_such_event", om.readTree("{}")));

        verifyNoInteractions(agentHub);
    }
}
