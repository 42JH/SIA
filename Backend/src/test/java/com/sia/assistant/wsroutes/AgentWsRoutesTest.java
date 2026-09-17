package com.sia.assistant.wsroutes;

import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

import com.sia.assistant.bootstrap.AgentBootstrapper;
import com.sia.assistant.gestureexec.GestureExecutor;
import com.sia.assistant.model.ModelManager;
import com.sia.assistant.registration.CalibrationOrchestrator;
import com.sia.assistant.registration.RegistrationOrchestrator;
import com.sia.assistant.registration.VoiceRegistrationOrchestrator;
import com.sia.assistant.relay.CameraPreviewRelay;
import com.sia.assistant.relay.EnrollmentRelay;
import com.sia.assistant.relay.MicPreviewRelay;
import com.sia.assistant.session.SessionService;
import com.sia.assistant.ws.FeHub;
import com.sia.assistant.ws.WsEvents;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.ObjectMapper;

/**
 * 온보딩 "이름 불러보기" 세 이벤트의 라우팅 (프로토콜 §4.1).
 * case 가 빠지면 default 로 조용히 버려지므로 중계 단위 테스트(EnrollmentRelayTest)로는 누락을 잡을 수 없다 —
 * wakeword_rejected 가 그렇게 빠져 있었다. 그래서 라우팅을 여기서 따로 고정한다.
 */
class AgentWsRoutesTest {

    private final ObjectMapper om = new ObjectMapper();
    private EnrollmentRelay enrollment;
    private FeHub feHub;
    private AgentWsRoutes routes;

    @BeforeEach
    void setUp() {
        enrollment = mock(EnrollmentRelay.class);
        feHub = mock(FeHub.class);
        routes = new AgentWsRoutes(feHub, mock(SessionService.class), mock(GestureExecutor.class),
                mock(RegistrationOrchestrator.class), mock(VoiceRegistrationOrchestrator.class),
                mock(CalibrationOrchestrator.class), enrollment, mock(ModelManager.class),
                mock(AgentBootstrapper.class), mock(CameraPreviewRelay.class), mock(MicPreviewRelay.class));
    }

    @Test
    @DisplayName("wakeword_rejected 는 페이로드째로 등록 중계로 넘어간다 — BE 가 해석하지 않는다")
    void rejectionIsRouted() throws Exception {
        routes.on(new WsEvents.AgentMessage("wakeword_rejected", om.readTree(
                "{\"n\":2,\"total\":5,\"reason\":\"또박또박 다시 불러주세요.\",\"code\":\"MISMATCH\"}")));

        verify(enrollment).onWakewordRejected(argThat(d ->
                d.path("n").asInt() == 2 && d.path("total").asInt() == 5
                        && "MISMATCH".equals(d.path("code").asText())));
        verifyNoInteractions(feHub);
    }

    @Test
    @DisplayName("샘플·완료도 같은 중계로 간다 — 세 이벤트가 한 자리에 모여 있어야 누락이 눈에 띈다")
    void sampleAndDoneAreRouted() throws Exception {
        routes.on(new WsEvents.AgentMessage("wakeword_sample", om.readTree("{\"n\":1,\"total\":5}")));
        routes.on(new WsEvents.AgentMessage("wakeword_done", om.readTree("{}")));

        verify(enrollment).onWakewordSample(argThat(d -> d.path("n").asInt() == 1));
        verify(enrollment).onWakewordDone();
    }

    @Test
    @DisplayName("모르는 type 은 조용히 무시된다")
    void unknownTypeIsIgnored() throws Exception {
        routes.on(new WsEvents.AgentMessage("no_such_event", om.readTree("{}")));

        verifyNoInteractions(enrollment, feHub);
    }
}
