package com.sia.assistant.ws;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.ConcurrentWebSocketSessionDecorator;
import org.springframework.web.socket.handler.TextWebSocketHandler;

/**
 * WS 허브 공통 기반. 모든 메시지는 {"type": "...", "data": {...}} 봉투다.
 * 송신은 구독자 전원 브로드캐스트 — FE 창이 여럿이어도, AI 프로세스가 재접속해도 동작이 같다.
 */
public abstract class BaseHub extends TextWebSocketHandler {

    private static final Logger log = LoggerFactory.getLogger(BaseHub.class);

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
                sendTo(session.getId(), "error", Map.of("message", "type 이 없습니다"));
                return;
            }
            onMessage(type, root.path("data"));
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
        } catch (IOException e) {
            log.error("[{}] '{}' 직렬화 실패", name(), type, e);
            return;
        }
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
            session.sendMessage(new TextMessage(om.writeValueAsString(envelope)));
        } catch (Exception e) {
            log.warn("[{}] 개별 전송 실패", name(), e);
        }
    }

    public boolean connected() {
        return !sessions.isEmpty();
    }

    protected abstract String name();

    protected abstract void onMessage(String type, JsonNode data);

    protected abstract void onConnected();

    protected abstract void onDisconnected();
}
