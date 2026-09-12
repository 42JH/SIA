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
 * 촬영 전 카메라 미리보기 중계 — AI 가 이미 열어 둔 카메라의 프레임을 FE 로 흘린다 (PROTOCOL.md §5·§6).
 *
 * <p>등록을 시작해야만 흐르는 {@code reg_frame} 으로는 "촬영 전에 내가 어떻게 잡히나"를 볼 수 없어서
 * 따로 뒀다. AI 는 {@code recognition_start} 이후 상시 인식을 위해 카메라를 계속 열고 있으므로
 * {@code cam_preview_start} 는 카메라를 새로 여는 지시가 아니라 <b>이미 도는 루프의 프레임을 보내라</b>는
 * 신호다 — 그래서 미리보기 중에도 제스처 인식이 멈추지 않는다.
 *
 * <p>이름에 {@code gesture_} 가 아니라 {@code cam_} 을 쓴 이유: 지금 부르는 곳은 제스처 등록 화면뿐이지만
 * 설정 화면의 카메라 확인 등으로 늘 수 있다. 등록 흐름에 묶이지 않은 독립 스위치다.
 *
 * <p><b>수명은 전부 BE 가 관리한다.</b> AI 는 start 로 켜고 stop 으로 끄기만 하면 된다:
 * <ul>
 *   <li>FE 가 stop 없이 사라지면(탭 닫기·새로고침·크래시) 마지막 구독자가 나갈 때 BE 가 대신 끊는다 —
 *       안 그러면 AI 가 아무도 보지 않는 프레임을 영원히 인코딩한다.</li>
 *   <li>실제 카메라 작업(등록·보정)이 시작되면 끝난 것으로 본다. 등록에서는 같은 프레임이
 *       {@code reg_frame} 으로 이중 송출되는 것을 막고, 보정에서는 보정 중 불필요한 전송을 막는다.</li>
 *   <li>stop 이후 늦게 도착한 프레임은 버린다 — AI 가 칼같이 멈출 필요가 없다.</li>
 * </ul>
 *
 * <p>등록과 달리 버퍼링 · 인코딩 · 저장이 없다. 받은 JPEG 를 그대로 흘리기만 한다.
 */
@Component
public class CameraPreviewRelay {

    private static final Logger log = LoggerFactory.getLogger(CameraPreviewRelay.class);

    private final AgentHub agentHub;
    private final FeHub feHub;

    /** 미리보기가 켜져 있는가 — 프레임을 FE 로 흘릴지, 중복 start 를 걸러낼지의 기준. */
    private final AtomicBoolean on = new AtomicBoolean(false);

    public CameraPreviewRelay(AgentHub agentHub, FeHub feHub) {
        this.agentHub = agentHub;
        this.feHub = feHub;
    }

    /** FE cam_preview_start → AI. AI 가 없으면 error 로 돌려준다 — 켜 봐야 프레임이 한 장도 안 온다. */
    public void start() {
        if (!agentHub.connected()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "AI 가 연결되어 있지 않습니다");
        }
        if (!on.compareAndSet(false, true)) {
            log.debug("카메라 미리보기가 이미 켜져 있어 AI 에 중복 전달하지 않는다");
            return;
        }
        agentHub.send("cam_preview_start", Map.of());
    }

    /** FE cam_preview_stop → AI. 이미 꺼져 있으면 아무것도 하지 않는다. */
    public void stop() {
        stopFor(null);
    }

    /**
     * 미리보기 종료. {@code reason} 이 있으면 FE 요청이 아니라 BE 판단으로 끊는 경우다
     * (FE 연결 종료 · 등록/보정 시작) — 왜 끊겼는지 로그에 남겨야 추적이 된다.
     */
    public void stopFor(String reason) {
        if (!on.compareAndSet(true, false)) {
            return;
        }
        if (reason != null) {
            log.info("카메라 미리보기 종료 — {}", reason);
        }
        agentHub.send("cam_preview_stop", Map.of());
    }

    /** AI cam_preview_state → FE 무해석 중계. STOPPED 는 이미 꺼진 뒤에 오므로 상태로 거르지 않는다. */
    public void onState(JsonNode d) {
        feHub.send("cam_preview_state", d != null && d.isObject() ? d : Map.of());
    }

    /** AI cam_preview_frame → FE. tsMs 는 BE 가 쓰지 않으므로 떼고, seq · jpegB64 만 넘긴다. */
    public void onFrame(JsonNode d) {
        if (!on.get()) {
            log.debug("꺼진 미리보기의 프레임 무시 (seq={})", d == null ? null : d.path("seq").asLong());
            return;
        }
        String jpegB64 = d == null ? "" : d.path("jpegB64").asText("");
        if (jpegB64.isBlank()) {
            log.warn("jpegB64 없는 미리보기 프레임 무시");
            return;
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("seq", d.path("seq").asLong());
        body.put("jpegB64", jpegB64);
        feHub.send("cam_preview_frame", body);
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
            log.info("AI 연결 종료 — 카메라 미리보기 상태 해제");
        }
    }
}
