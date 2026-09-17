package com.sia.assistant.wsroutes;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

import com.sia.assistant.registration.CalibrationOrchestrator;
import com.sia.assistant.registration.RegistrationOrchestrator;
import com.sia.assistant.registration.VoiceRegistrationOrchestrator;
import com.sia.assistant.relay.CameraPreviewRelay;
import com.sia.assistant.relay.EnrollmentRelay;
import com.sia.assistant.relay.MicPreviewRelay;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.WsEvents;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
import tools.jackson.databind.ObjectMapper;

/**
 * user_choice — AI 가 notice(kind:"choices")로 띄운 후보 목록의 클릭 응답 중계.
 * AI↔FE 직접 채널이 없으므로 BE 가 무해석으로 AI 에 넘긴다 (PROTOCOL.md §0·§2).
 */
class FeWsRoutesTest {

    private final ObjectMapper om = new ObjectMapper();
    private AgentHub agentHub;
    private RegistrationOrchestrator registration;
    private CalibrationOrchestrator calibration;
    private CameraPreviewRelay cameraPreview;
    private MicPreviewRelay micPreview;
    private VoiceRegistrationOrchestrator voiceRegistration;
    private EnrollmentRelay enrollment;
    private FeWsRoutes routes;

    @BeforeEach
    void setUp() {
        agentHub = mock(AgentHub.class);
        registration = mock(RegistrationOrchestrator.class);
        calibration = mock(CalibrationOrchestrator.class);
        cameraPreview = mock(CameraPreviewRelay.class);
        micPreview = mock(MicPreviewRelay.class);
        voiceRegistration = mock(VoiceRegistrationOrchestrator.class);
        enrollment = mock(EnrollmentRelay.class);
        routes = new FeWsRoutes(agentHub, registration, voiceRegistration, calibration,
                enrollment, cameraPreview, micPreview);
    }

    @Test
    @DisplayName("reg_start 는 등록을 시작하기 전에 카메라 미리보기를 끈다 — reg_frame 과 이중 송출되지 않게")
    void regStartStopsPreviewFirst() throws Exception {
        routes.on(new WsEvents.FeMessage("reg_start", om.readTree("{\"motion\":\"STATIC\"}")));

        InOrder order = inOrder(cameraPreview, registration);
        order.verify(cameraPreview).stopFor(anyString());
        order.verify(registration).start(null, "STATIC");
    }

    @Test
    @DisplayName("calib_start 도 미리보기를 끈다 — 보정 중에는 영상을 FE 로 보내지 않는다")
    void calibStartStopsPreview() throws Exception {
        routes.on(new WsEvents.FeMessage("calib_start", om.readTree("{}")));

        InOrder order = inOrder(cameraPreview, calibration);
        order.verify(cameraPreview).stopFor(anyString());
        order.verify(calibration).start();
    }

    @Test
    @DisplayName("등록이 시작돼도 마이크 미리보기는 끊지 않는다 — 말하는 동안 파형이 움직여야 한다")
    void registrationDoesNotStopMicPreview() throws Exception {
        routes.on(new WsEvents.FeMessage("voice_reg_start", om.readTree("{}")));
        routes.on(new WsEvents.FeMessage("reg_start", om.readTree("{}")));
        routes.on(new WsEvents.FeMessage("calib_start", om.readTree("{}")));

        verify(voiceRegistration).start();
        verifyNoInteractions(micPreview);
    }

    @Test
    @DisplayName("user_choice 는 페이로드 그대로 AI 로 중계된다 — BE 는 해석하지 않는다")
    void userChoiceIsRelayedVerbatim() throws Exception {
        routes.on(new WsEvents.FeMessage("user_choice",
                om.readTree("{\"choiceId\":\"c-7f31\",\"n\":1}")));

        verify(agentHub).send(eq("user_choice"), argThat(d ->
                d instanceof tools.jackson.databind.JsonNode node
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
    @DisplayName("wakeword_enroll_cancel 은 등록 중계로 넘어간다 — 보이스의 voice_reg_cancel 과 같은 자리")
    void wakewordCancelIsRouted() throws Exception {
        routes.on(new WsEvents.FeMessage("wakeword_enroll_cancel", om.readTree("{}")));

        verify(enrollment).cancelWakeword();
    }

    @Test
    @DisplayName("모르는 type 은 조용히 무시된다")
    void unknownTypeIsIgnored() throws Exception {
        routes.on(new WsEvents.FeMessage("no_such_event", om.readTree("{}")));

        verifyNoInteractions(agentHub);
    }
}
