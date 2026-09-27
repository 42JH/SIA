package com.sia.assistant.wsroutes;

import com.sia.assistant.registration.CalibrationOrchestrator;
import com.sia.assistant.registration.RegistrationOrchestrator;
import com.sia.assistant.registration.VoiceRegistrationOrchestrator;
import com.sia.assistant.relay.CameraPreviewRelay;
import com.sia.assistant.relay.EnrollmentRelay;
import com.sia.assistant.relay.MicPreviewRelay;
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
    private final CameraPreviewRelay cameraPreview;
    private final MicPreviewRelay micPreview;

    public FeWsRoutes(AgentHub agentHub, RegistrationOrchestrator registration,
                      VoiceRegistrationOrchestrator voiceRegistration,
                      CalibrationOrchestrator calibration, EnrollmentRelay enrollment,
                      CameraPreviewRelay cameraPreview, MicPreviewRelay micPreview) {
        this.agentHub = agentHub;
        this.registration = registration;
        this.voiceRegistration = voiceRegistration;
        this.calibration = calibration;
        this.enrollment = enrollment;
        this.cameraPreview = cameraPreview;
        this.micPreview = micPreview;
    }

    @EventListener
    public void on(WsEvents.FeMessage msg) {
        JsonNode d = msg.data();
        switch (msg.type()) {
            // ---- 촬영 전 카메라 미리보기 (등록 흐름과 독립 — 설정 화면 등에서도 쓴다)
            case "cam_preview_start" -> cameraPreview.start();
            case "cam_preview_stop" -> cameraPreview.stop();
            // ---- 마이크 입력 레벨 미리보기 (등록 흐름과 독립 — 호출어 · 보이스 등록 화면의 파형)
            //      카메라와 달리 등록이 시작돼도 끊지 않는다 — 말하는 동안 파형이 움직여야 하는 게 목적이다
            case "mic_preview_start" -> micPreview.start();
            case "mic_preview_stop" -> micPreview.stop();
            // ---- 커스텀 제스처 (3회 촬영 · motion 은 정적/동적 등록 창 · replaceGestureId 면 동작 재촬영)
            //      실제 촬영이 시작되면 미리보기는 끝이다 — 같은 카메라가 reg_frame 으로 이중 송출되지 않게
            case "reg_start" -> {
                cameraPreview.stopFor("제스처 등록 시작");
                registration.start(
                        d.hasNonNull("replaceGestureId") ? d.path("replaceGestureId").asLong() : null,
                        d.hasNonNull("motion") ? d.path("motion").asText() : null);
            }
            case "reg_stop" -> registration.stop(d.path("tempId").asText());
            case "macro_assign" -> registration.assign(d);
            // ---- 온보딩 · 호출어 변경: 이름 불러보기
            //      wakeWord 는 선택 — 없으면 지금 설정된 호출어로 등록한다 (온보딩). 확정은 wakeword_done 때다
            case "wakeword_enroll_start" -> enrollment.startWakeword(d);
            //      취소는 tempId 를 받지 않는다 — 호출어 템플릿은 전역 1개라 지목할 대상이 없다
            case "wakeword_enroll_cancel" -> enrollment.cancelWakeword();
            // ---- 보이스 등록 (5문장 → 녹음 확인 → 등록) — 온보딩의 "명령하듯 말해보세요" 단계가 곧 이것이다
            //      문장 진행은 사용자 확인(voice_sentence_next)이 방아쇠다 — 통과만으로 넘어가지 않는다
            case "voice_reg_start" -> voiceRegistration.start();
            case "voice_sentence_next" -> voiceRegistration.nextSentence(d.path("tempId").asText());
            case "voice_sentence_retry" -> voiceRegistration.retrySentence(d.path("tempId").asText());
            case "voice_reg_retry" -> voiceRegistration.retryAll(d.path("tempId").asText());
            case "voice_accept_anyway" -> voiceRegistration.acceptAnyway(d.path("tempId").asText());
            case "voice_commit" -> voiceRegistration.commit(d.path("tempId").asText(),
                    d.hasNonNull("name") ? d.path("name").asText() : null,
                    d.hasNonNull("deviceLabel") ? d.path("deviceLabel").asText() : null);
            case "voice_reg_cancel" -> voiceRegistration.cancel(d.path("tempId").asText());
            // ---- 시선 보정 (재측정 최대 3회 — BE 가 센다)
            case "calib_start" -> {
                cameraPreview.stopFor("시선 보정 시작"); // 보정 중에는 프리뷰를 보내지 않는다 (자세 안내는 calib_precheck)
                calibration.start();
            }
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
