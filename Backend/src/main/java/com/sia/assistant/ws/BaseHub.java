package com.sia.assistant.ws;

import com.sia.assistant.common.LogPreview;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.ConcurrentWebSocketSessionDecorator;
import org.springframework.web.socket.handler.TextWebSocketHandler;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * WS 허브 공통 기반. 모든 메시지는 {"type": "...", "data": {...}} 봉투다.
 * 송신은 구독자 전원 브로드캐스트 — FE 창이 여럿이어도, AI 프로세스가 재접속해도 동작이 같다.
 */
public abstract class BaseHub extends TextWebSocketHandler {

    private static final Logger log = LoggerFactory.getLogger(BaseHub.class);

    /**
     * 초당 수십 번 오가거나(gaze_cursor·ping/pong) 수백 KB 짜리(reg_frame)라 INFO 로 찍으면
     * 콘솔이 잠기는 type — 이것들만 DEBUG 로 내린다. 나머지 송수신은 전부 INFO 다.
     */
    private static final Set<String> NOISY =
            Set.of("gaze_cursor", "reg_frame", "cam_preview_frame", "mic_preview_level", "ping", "pong");

    /** 원본 세션 id → 동시 전송 안전 데코레이터 */
    private final Map<String, WebSocketSession> sessions = new ConcurrentHashMap<>();
    private final ObjectMapper om;

    protected BaseHub(ObjectMapper om) {
        this.om = om;
    }

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        sessions.put(session.getId(),
                new ConcurrentWebSocketSessionDecorator(session, 10_000, 4 * 1024 * 1024));
        log.info("[{}] 연결 — 구독자 {}", name(), sessions.size());
        onConnected();
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        sessions.remove(session.getId());
        log.info("[{}] 종료({}) — 구독자 {}", name(), status.getCode(), sessions.size());
        onDisconnected();
    }

    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) {
        String type = null;
        try {
            JsonNode root = om.readTree(message.getPayload());
            type = root.path("type").asText(null);
            if (type == null || type.isBlank()) {
                log.warn("[{}] <- type 없는 메시지 {}", name(), preview(message.getPayload()));
                sendTo(session.getId(), "error", Map.of("message", "type 이 없습니다"));
                return;
            }
            JsonNode data = root.path("data");
            logTraffic("<-", type, data);
            onMessage(type, data);
        } catch (Exception e) {
            log.warn("[{}] '{}' 처리 실패", name(), type, e);
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("message", e.getMessage() == null ? "처리에 실패했습니다" : e.getMessage());
            if (type != null) {
                body.put("of", type);
            }
            sendTo(session.getId(), "error", body);
        }
    }

    /** 구독자 전원에게 송신. 전송이 실패한 구독자는 즉시 제거한다. */
    public void send(String type, Object data) {
        if (sessions.isEmpty()) {
            return;
        }
        TextMessage msg;
        try {
            Map<String, Object> envelope = new LinkedHashMap<>();
            envelope.put("type", type);
            envelope.put("data", data == null ? Map.of() : data);
            msg = new TextMessage(om.writeValueAsString(envelope));
        } catch (JacksonException e) {
            // Jackson 3 의 직렬화 예외는 unchecked 다 — 여기서 잡지 않으면 이벤트 하나가 호출자까지 터뜨린다
            log.error("[{}] '{}' 직렬화 실패", name(), type, e);
            return;
        }
        logTraffic("->", type, data);
        for (Map.Entry<String, WebSocketSession> entry : sessions.entrySet()) {
            try {
                entry.getValue().sendMessage(msg);
            } catch (Exception e) {
                log.warn("[{}] 전송 실패 — 구독자 제거: {}", name(), e.toString());
                sessions.remove(entry.getKey());
                try {
                    entry.getValue().close();
                } catch (IOException ignored) {
                }
            }
        }
    }

    private void sendTo(String sessionId, String type, Object data) {
        WebSocketSession session = sessions.get(sessionId);
        if (session == null) {
            return;
        }
        try {
            Map<String, Object> envelope = new LinkedHashMap<>();
            envelope.put("type", type);
            envelope.put("data", data == null ? Map.of() : data);
            String json = om.writeValueAsString(envelope);
            log.info("[{}] -> {} (개별 회신) {}", name(), type, preview(json));
            session.sendMessage(new TextMessage(json));
        } catch (Exception e) {
            log.warn("[{}] 개별 전송 실패", name(), e);
        }
    }

    /**
     * 송수신 한 건을 한 줄로 — 방향·type·페이로드 미리보기. 시끄러운 type 만 DEBUG 다.
     * 페이로드 직렬화는 그 레벨이 켜져 있을 때만 한다 (reg_frame 수백 KB 를 헛되이 두 번 만들지 않는다).
     */
    private void logTraffic(String arrow, String type, Object data) {
        boolean noisy = NOISY.contains(type);
        if (noisy ? !log.isDebugEnabled() : !log.isInfoEnabled()) {
            return;
        }
        String json;
        try {
            json = om.writeValueAsString(data == null || (data instanceof JsonNode n && n.isMissingNode())
                    ? Map.of() : data);
        } catch (JacksonException e) {
            json = "(직렬화 불가)";
        }
        if (noisy) {
            log.debug("[{}] {} {} {}", name(), arrow, type, preview(json));
        } else {
            log.info("[{}] {} {} {}", name(), arrow, type, preview(json));
        }
    }

    private static String preview(String json) {
        return LogPreview.of(json);
    }

    public boolean connected() {
        return !sessions.isEmpty();
    }

    protected abstract String name();

    protected abstract void onMessage(String type, JsonNode data);

    protected abstract void onConnected();

    protected abstract void onDisconnected();
}
