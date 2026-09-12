package com.sia.assistant.wsroutes;

import com.sia.assistant.bootstrap.AgentBootstrapper;
import com.sia.assistant.gestureexec.GestureExecutor;
import com.sia.assistant.model.ModelManager;
import com.sia.assistant.registration.CalibrationOrchestrator;
import com.sia.assistant.registration.RegistrationOrchestrator;
import com.sia.assistant.registration.VoiceRegistrationOrchestrator;
import com.sia.assistant.relay.CameraPreviewRelay;
import com.sia.assistant.relay.EnrollmentRelay;
import com.sia.assistant.session.SessionService;
import com.sia.assistant.ws.FeHub;
import com.sia.assistant.ws.WsEvents;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

/**
 * /ws/agent 수신 라우터 — PROTOCOL.md §1 의 AI→BE 이벤트 전부.
 * 여기서 예외가 나면 BaseHub 가 발신자에게 error {message, of} 를 회신한다.
 */
@Component
public class AgentWsRoutes {

    private static final Logger log = LoggerFactory.getLogger(AgentWsRoutes.class);

    private final FeHub feHub;
    private final SessionService sessionService;
    private final GestureExecutor gestureExecutor;
    private final RegistrationOrchestrator registration;
    private final VoiceRegistrationOrchestrator voiceRegistration;
    private final CalibrationOrchestrator calibration;
    private final EnrollmentRelay enrollment;
    private final ModelManager modelManager;
    private final AgentBootstrapper bootstrapper;
    private final CameraPreviewRelay cameraPreview;

    public AgentWsRoutes(FeHub feHub, SessionService sessionService,
                         GestureExecutor gestureExecutor, RegistrationOrchestrator registration,
                         VoiceRegistrationOrchestrator voiceRegistration, CalibrationOrchestrator calibration,
                         EnrollmentRelay enrollment, ModelManager modelManager,
                         AgentBootstrapper bootstrapper, CameraPreviewRelay cameraPreview) {
        this.feHub = feHub;
        this.sessionService = sessionService;
        this.gestureExecutor = gestureExecutor;
        this.registration = registration;
        this.voiceRegistration = voiceRegistration;
        this.calibration = calibration;
        this.enrollment = enrollment;
        this.modelManager = modelManager;
        this.bootstrapper = bootstrapper;
        this.cameraPreview = cameraPreview;
    }

    @EventListener
    public void on(WsEvents.AgentMessage msg) {
        JsonNode d = msg.data();
        switch (msg.type()) {
            case "hello" -> bootstrapper.onHello(d);
            case "wakeword_detected" -> {
                // FE 반응이 먼저다 — 사용자가 말을 잇는 동안 이미 화면이 반응해야 한다
                feHub.send("listening", Map.of());
                // ★ 세션 시작 시각 = BE 가 이 이벤트를 받은 순간. 활성이면 아무것도 하지 않는다
                sessionService.openOnWakeword();
            }
            case "session_open" -> sessionService.open(d.path("trigger").asText(null));
            case "session_renew" -> sessionService.renew(longOrNull(d, "sessionId"));
            case "session_end" -> sessionService.end(longOrNull(d, "sessionId"),
                    d.path("reason").asText("STOPPED"));
            // transcript(명령 실패 시 인식된 말)까지 그대로 FE 로 — 표시용 중계일 뿐, 저장하지 않는다
            case "notice" -> feHub.send("notice", passthrough(d));
            // 시선 커서 좌표 — 설정 gazeCursor 가 켜졌을 때만 AI 가 보낸다. 저장·로그 없이 그대로 흘린다
            case "gaze_cursor" -> feHub.send("gaze_cursor", passthrough(d));
            // 화자 게이트 기각 — HUD "등록된 목소리로 한 명령이 아닙니다" (통계는 events 배치가 따로 든다)
            case "voice_rejected" -> feHub.send("voice_rejected",
                    Map.of("message", "등록된 목소리로 한 명령이 아닙니다."));
            case "gesture_exec" -> gestureExecutor.execute(d);
            // ---- 촬영 전 카메라 미리보기 — 저장 없이 그대로 FE 로 흘린다
            case "cam_preview_state" -> cameraPreview.onState(d);
            case "cam_preview_frame" -> cameraPreview.onFrame(d);
            case "reg_started" -> registration.onRegStarted(d.path("tempId").asText());
            case "reg_take" -> registration.onTake(d.path("tempId").asText(), d);
            case "reg_frame" -> registration.onFrame(d.path("tempId").asText(),
                    d.path("take").asInt(1), d.path("seq").asLong(), d.path("tsMs").asLong(),
                    d.path("jpegB64").asText());
            case "reg_rejected" -> registration.onRejected(d.path("tempId").asText(), d);
            case "reg_captured" -> registration.onCaptured(d.path("tempId").asText(), d);
            // ---- 온보딩: 이름 불러보기
            case "wakeword_sample" -> enrollment.onWakewordSample(d);
            case "wakeword_done" -> enrollment.onWakewordDone();
            // ---- 보이스 등록 (5문장) — 온보딩의 "명령하듯 말해보세요" 단계가 곧 이것이다
            case "voice_ready" -> voiceRegistration.onReady(d.path("tempId").asText());
            case "voice_progress" -> voiceRegistration.onProgress(d.path("tempId").asText(),
                    d.path("n").asInt());
            case "voice_sentence_rejected" -> voiceRegistration.onSentenceRejected(d.path("tempId").asText(), d);
            case "voice_quality_warn" -> voiceRegistration.onQualityWarn(d.path("tempId").asText(), d);
            case "voice_captured" -> voiceRegistration.onCaptured(d.path("tempId").asText(), d);
            // ---- 시선 보정 (9점 두더지 · 재측정 3회는 BE 카운트)
            case "calib_precheck" -> calibration.onPrecheck(d);
            case "calib_point_ready" -> calibration.onPointReady(d);
            case "calib_point_done" ->
                    log.debug("calib_point_done n={}", d.path("n").asInt()); // 점 단위 핸드셰이크 — BE 액션 없음
            case "calib_result" -> calibration.onResult(d.path("tempId").asText(), d);
            case "model_loaded" -> modelManager.onModelLoaded(d.path("name").asText());
            case "model_load_failed" -> modelManager.onModelLoadFailed(d.path("name").asText(),
                    d.path("reason").asText(""));
            case "recognition_started" -> bootstrapper.onRecognitionStarted();
            default -> log.debug("[ws/agent] 모르는 type 무시: {}", msg.type());
        }
    }

    private static Long longOrNull(JsonNode d, String field) {
        return d.hasNonNull(field) ? d.path(field).asLong() : null;
    }

    /** 중계는 받은 페이로드 그대로 — 객체가 아니면 빈 객체로 방어. */
    private static Object passthrough(JsonNode d) {
        return d != null && d.isObject() ? d : Map.of();
    }
}
