package com.sia.assistant.domtext;

import com.fasterxml.jackson.databind.JsonNode;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.ExtHub;
import jakarta.annotation.PreDestroy;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * dom_text 중계 — AI 의 dom_text_request 를 브라우저 확장(/ws/ext)으로 넘기고 응답을 AI 에 돌려준다.
 * AI 쪽 계약(dom_text_request {} → dom_text {available, ...})은 그대로 두고,
 * requestId 상관관계는 BE↔확장 사이에서만 쓴다. 확장 미연결·무응답은 {available:false, reason} 으로 환원한다.
 */
@Component
public class DomTextService {

    private static final Logger log = LoggerFactory.getLogger(DomTextService.class);

    private static final long TIMEOUT_MS = 4000;
    /** LLM 컨텍스트 보호 — 확장도 자르지만 서버에서 한 번 더 강제한다. */
    private static final int MAX_TEXT_CHARS = 20000;

    private final ExtHub extHub;
    private final AgentHub agentHub;
    private final Map<String, ScheduledFuture<?>> pending = new ConcurrentHashMap<>();

    private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
        Thread t = new Thread(r, "dom-text-timeout");
        t.setDaemon(true);
        return t;
    });

    public DomTextService(ExtHub extHub, AgentHub agentHub) {
        this.extHub = extHub;
        this.agentHub = agentHub;
    }

    /** AI 의 dom_text_request 처리. */
    public void request() {
        if (!extHub.connected()) {
            unavailable("브라우저 확장이 연결되어 있지 않습니다");
            return;
        }
        String requestId = UUID.randomUUID().toString().substring(0, 8);
        ScheduledFuture<?> timeout = scheduler.schedule(() -> expire(requestId), TIMEOUT_MS, TimeUnit.MILLISECONDS);
        pending.put(requestId, timeout);
        extHub.send("dom_text_request", Map.of("requestId", requestId));
    }

    /** 확장의 dom_text 응답 처리. */
    public void onReply(JsonNode d) {
        String requestId = d.path("requestId").asText("");
        ScheduledFuture<?> timeout = pending.remove(requestId);
        if (timeout == null) {
            log.debug("만료되었거나 모르는 dom_text 응답 무시: {}", requestId);
            return;
        }
        timeout.cancel(false);

        if (!d.path("available").asBoolean(false)) {
            unavailable(d.path("reason").asText("본문을 추출하지 못했습니다"));
            return;
        }
        String text = d.path("text").asText("");
        boolean truncated = d.path("truncated").asBoolean(false);
        if (text.length() > MAX_TEXT_CHARS) {
            text = text.substring(0, MAX_TEXT_CHARS);
            truncated = true;
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("available", true);
        body.put("url", d.path("url").asText(null));
        body.put("title", d.path("title").asText(null));
        body.put("text", text);
        body.put("truncated", truncated);
        agentHub.send("dom_text", body);
    }

    private void expire(String requestId) {
        if (pending.remove(requestId) != null) {
            unavailable("브라우저 확장이 응답하지 않습니다");
        }
    }

    private void unavailable(String reason) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("available", false);
        body.put("reason", reason);
        agentHub.send("dom_text", body);
    }

    @PreDestroy
    void shutdown() {
        scheduler.shutdownNow();
    }
}
