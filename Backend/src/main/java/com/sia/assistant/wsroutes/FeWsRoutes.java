package com.sia.assistant.wsroutes;

import com.sia.assistant.registration.CalibrationOrchestrator;
import com.sia.assistant.registration.RegistrationOrchestrator;
import com.sia.assistant.registration.VoiceRegistrationOrchestrator;
import com.sia.assistant.relay.EnrollmentRelay;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.WsEvents;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

/**
 * /ws/fe 수신 라우터 — PROTOCOL.md §2 의 FE→BE 이벤트 전부.
 * 여기서 예외가 나면 BaseHub 가 발신자에게 error {message, of} 를 회신한다.
 */
@Component
public class FeWsRoutes {

    private static final Logger log = LoggerFactory.getLogger(FeWsRoutes.class);

    private final AgentHub agentHub;
    private final RegistrationOrchestrator registration;
    private final VoiceRegistrationOrchestrator voiceRegistration;
    private final CalibrationOrchestrator calibration;
    private final EnrollmentRelay enrollment;

    public FeWsRoutes(AgentHub agentHub, RegistrationOrchestrator registration,
                      VoiceRegistrationOrchestrator voiceRegistration,
                      CalibrationOrchestrator calibration, EnrollmentRelay enrollment) {
        this.agentHub = agentHub;
        this.registration = registration;
        this.voiceRegistration = voiceRegistration;
        this.calibration = calibration;
        this.enrollment = enrollment;
    }

    @EventListener
    public void on(WsEvents.FeMessage msg) {
        JsonNode d = msg.data();
        switch (msg.type()) {
            // ---- 커스텀 제스처 (3회 촬영 · replaceGestureId 면 동작 재촬영)
            case "reg_start" -> registration.start(
                    d.hasNonNull("replaceGestureId") ? d.path("replaceGestureId").asLong() : null);
            case "reg_stop" -> registration.stop(d.path("tempId").asText());
            case "macro_assign" -> registration.assign(d);
            // ---- 온보딩: 이름 불러보기 · 명령 문장 말하기
            case "wakeword_enroll_start" -> enrollment.startWakeword();
            case "command_enroll_start" -> enrollment.startCommand();
            // ---- 보이스 등록 (5문장 → 녹음 확인 → 등록)
            case "voice_reg_start" -> voiceRegistration.start();
            case "voice_sentence_retry" -> voiceRegistration.retrySentence(d.path("tempId").asText());
            case "voice_reg_retry" -> voiceRegistration.retryAll(d.path("tempId").asText());
            case "voice_accept_anyway" -> voiceRegistration.acceptAnyway(d.path("tempId").asText());
            case "voice_commit" -> voiceRegistration.commit(d.path("tempId").asText(),
                    d.hasNonNull("name") ? d.path("name").asText() : null,
                    d.hasNonNull("deviceLabel") ? d.path("deviceLabel").asText() : null);
            case "voice_reg_cancel" -> voiceRegistration.cancel(d.path("tempId").asText());
            // ---- 시선 보정 (재측정 최대 3회 — BE 가 센다)
            case "calib_start" -> calibration.start();
            case "calib_point_shown" -> calibration.onPointShown(d.path("n").asInt(),
                    d.hasNonNull("x") ? d.path("x").asInt() : null,
                    d.hasNonNull("y") ? d.path("y").asInt() : null);
            case "calib_restart" -> calibration.restart();
            case "calib_commit" -> calibration.commit(
                    d.hasNonNull("name") ? d.path("name").asText() : null,
                    d.hasNonNull("deviceLabel") ? d.path("deviceLabel").asText() : null);
            case "calib_cancel" -> calibration.cancel();
            // ---- AI 가 notice(kind:"choices")로 띄운 후보 목록의 클릭 응답 — AI↔FE 직접 채널이
            //      없으므로 BE 가 무해석 중계한다. 필드(choiceId·n·cancelled)는 AI↔FE 계약이다.
            case "user_choice" -> agentHub.send("user_choice", passthrough(d));
            default -> log.debug("[ws/fe] 모르는 type 무시: {}", msg.type());
        }
    }

    /** 중계는 받은 페이로드 그대로 — 객체가 아니면 빈 객체로 방어. */
    private static Object passthrough(JsonNode d) {
        return d != null && d.isObject() ? d : Map.of();
    }
}
