package com.sia.assistant.relay;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import com.sia.assistant.ws.WsEvents;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

/**
 * 마이크 입력 레벨 중계 — AI 가 이미 열어 둔 마이크의 진폭을 FE 로 흘려 파형을 그리게 한다 (프로토콜 §5.5).
 *
 * <p>호출어 등록 · 보이스 등록 화면에서 "내 목소리가 들어가고 있나"를 눈으로 확인시키는 경로다.
 * 등록 흐름은 순번(<code>wakeword_progress</code> · <code>voice_progress</code>)만 알려줄 뿐
 * 말하는 동안에는 아무 신호가 없어서, 사용자는 녹음이 끝나고 판독 결과가 뜰 때까지
 * 마이크가 죽었는지 살았는지 알 수 없었다.
 *
 * <p>{@link CameraPreviewRelay} 의 마이크 판이고 수명 규칙도 같다. AI 는 {@code recognition_start}
 * 이후 호출어 상시 감지를 위해 마이크를 계속 열고 있으므로 {@code mic_preview_start} 는 마이크를
 * 새로 여는 지시가 아니라 <b>이미 도는 루프의 진폭을 보내라</b>는 신호다 — 그래서 미리보기 중에도
 * 호출어 감지가 멈추지 않고, 준비 단계가 없어 {@code STARTING} 없이 바로 {@code READY} 가 온다.
 *
 * <p><b>카메라와 다른 점이 하나 있다.</b> 카메라 미리보기는 실제 촬영({@code reg_start} ·
 * {@code calib_start})이 시작되면 BE 가 껐다 — 같은 프레임이 {@code reg_frame} 으로 이중 송출되는 것을
 * 막기 위해서다. 마이크는 반대로 <b>등록이 진행되는 동안 계속 흘러야 한다</b>. 파형을 보여주려는 때가
 * 바로 그 때이고, 레벨은 등록 경로로 이중 송출되지도 않는다. 그래서 등록 시작에 끊는 규칙이 없고,
 * BE 가 대신 끊는 경우는 마지막 FE 구독자가 나갈 때 하나뿐이다.
 *
 * <p>이름에 {@code voice_} 가 아니라 {@code mic_} 을 쓴 이유는 카메라와 같다: 지금 부르는 곳은
 * 온보딩 마이크 설정과 보이스 등록이지만 설정 화면의 마이크 확인 등으로 늘 수 있다.
 * 등록 흐름에 묶이지 않은 독립 스위치다.
 *
 * <p>버퍼링 · 인코딩 · 저장이 없다. 한 메시지가 그 순간의 진폭 하나이고(배열로 묶지 않는다 —
 * 묶는 만큼 파형이 늦게 움직인다) 받는 즉시 흘린다. 권장 주기는 {@code gaze_cursor} 와 같은 10~30Hz 다.
 */
@Component
public class MicPreviewRelay {

    private static final Logger log = LoggerFactory.getLogger(MicPreviewRelay.class);

    private final AgentHub agentHub;
    private final FeHub feHub;

    /** 미리보기가 켜져 있는가 — 레벨을 FE 로 흘릴지, 중복 start 를 걸러낼지의 기준. */
    private final AtomicBoolean on = new AtomicBoolean(false);

    public MicPreviewRelay(AgentHub agentHub, FeHub feHub) {
        this.agentHub = agentHub;
        this.feHub = feHub;
    }

    /** FE mic_preview_start → AI. AI 가 없으면 error 로 돌려준다 — 켜 봐야 레벨이 하나도 안 온다. */
    public void start() {
        if (!agentHub.connected()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "AI 가 연결되어 있지 않습니다");
        }
        if (!on.compareAndSet(false, true)) {
            log.debug("마이크 미리보기가 이미 켜져 있어 AI 에 중복 전달하지 않는다");
            return;
        }
        agentHub.send("mic_preview_start", Map.of());
    }

    /** FE mic_preview_stop → AI. 이미 꺼져 있으면 아무것도 하지 않는다. */
    public void stop() {
        stopFor(null);
    }

    /**
     * 미리보기 종료. {@code reason} 이 있으면 FE 요청이 아니라 BE 판단으로 끊는 경우다
     * (FE 연결 종료) — 왜 끊겼는지 로그에 남겨야 추적이 된다.
     */
    public void stopFor(String reason) {
        if (!on.compareAndSet(true, false)) {
            return;
        }
        if (reason != null) {
            log.info("마이크 미리보기 종료 — {}", reason);
        }
        agentHub.send("mic_preview_stop", Map.of());
    }

    /** AI mic_preview_state → FE 무해석 중계. STOPPED 는 이미 꺼진 뒤에 오므로 상태로 거르지 않는다. */
    public void onState(JsonNode d) {
        feHub.send("mic_preview_state", d != null && d.isObject() ? d : Map.of());
    }

    /**
     * AI mic_preview_level → FE. seq · level 만 넘긴다.
     *
     * <p>빠진 {@code level} 을 0 으로 읽으면 무음과 구분이 안 되므로 숫자일 때만 받는다.
     * 반대로 범위를 벗어난 값은 버리지 않고 0~1 로 자른다 — 포화 한 번에 막대가 빠지면
     * 파형이 끊겨 보이는데, 그건 잘못된 값을 그리는 것보다 나쁘다.
     */
    public void onLevel(JsonNode d) {
        if (!on.get()) {
            log.debug("꺼진 미리보기의 레벨 무시 (seq={})", d == null ? null : d.path("seq").asLong());
            return;
        }
        JsonNode level = d == null ? null : d.path("level");
        if (level == null || !level.isNumber() || !Double.isFinite(level.asDouble())) {
            log.warn("level 없는 미리보기 레벨 무시");
            return;
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("seq", d.path("seq").asLong());
        body.put("level", Math.clamp(level.asDouble(), 0.0, 1.0));
        feHub.send("mic_preview_level", body);
    }

    /**
     * FE 소켓 종료 — 마지막 구독자가 나갈 때만 끊는다. 탭이 여러 개면 하나가 닫혀도 나머지가 보고 있다.
     */
    @EventListener
    public void onFeDisconnected(WsEvents.FeDisconnected e) {
        if (feHub.connected()) {
            return;
        }
        stopFor("FE 연결 종료");
    }

    /** AI 가 나가면 보낼 곳이 없다 — stop 을 보내지 않고 상태만 내린다. */
    @EventListener
    public void onAgentDisconnected(WsEvents.AgentDisconnected e) {
        if (on.compareAndSet(true, false)) {
            log.info("AI 연결 종료 — 마이크 미리보기 상태 해제");
        }
    }
}
