package com.sia.assistant.domtext;

import com.fasterxml.jackson.databind.JsonNode;
import com.sia.assistant.control.browser.BrowserTextService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.ExtHub;
import com.sia.assistant.ws.FeHub;
import jakarta.annotation.PreDestroy;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * dom_text 중계 — AI 의 dom_text_request 에 페이지 본문을 돌려준다. 공급원이 둘이다.
 *
 * <p><b>확장이 붙어 있으면</b> /ws/ext 로 중계한다 ({@code via: "extension"}). AI 쪽 계약
 * (dom_text_request {} → dom_text {available, ...})은 그대로 두고, requestId 상관관계는
 * BE↔확장 사이에서만 쓴다. 무응답은 4초에 끊는다.
 *
 * <p><b>확장이 없으면</b> 화면 접근성(UIA)으로 브라우저 창을 직접 읽는다 ({@code via: "accessibility"}).
 * 본문만 골라내지 못해 메뉴·사이드바가 섞이므로 AI 가 품질을 알도록 via 를 싣고, 사용자에게는
 * FE 팝업(notice)으로 확장이 없다는 사실을 알린다.
 *
 * <p>★ notice 는 원래 AI 가 소유하는 채널이지만(AI → BE → FE) 이 한 건은 BE 가 직접 보낸다 —
 * 확장 부재는 대화가 아니라 시스템 상태이고, AI 가 언급을 생략해도 사용자는 알아야 하기 때문이다.
 * 프로토콜.md §6.6 에 예외로 적어 두었다.
 */
@Component
public class DomTextService {

    private static final Logger log = LoggerFactory.getLogger(DomTextService.class);

    private static final long TIMEOUT_MS = 4000;
    /** LLM 컨텍스트 보호 — 확장도 자르지만 서버에서 한 번 더 강제한다. */
    private static final int MAX_TEXT_CHARS = 20000;

    private static final String VIA_EXTENSION = "extension";
    private static final String VIA_ACCESSIBILITY = "accessibility";

    /** 같은 팝업이 연달아 뜨지 않게 하는 간격. 한 번의 발화가 dom_text 를 여러 번 부를 수 있다. */
    private static final long NOTICE_INTERVAL_MS = 60_000;

    private final ExtHub extHub;
    private final AgentHub agentHub;
    private final FeHub feHub;
    private final BrowserTextService browserTextService;
    private final Map<String, ScheduledFuture<?>> pending = new ConcurrentHashMap<>();
    private final AtomicLong lastNoticeAt = new AtomicLong(0);

    private final ScheduledExecutorService scheduler = Executors.newSingleThreadScheduledExecutor(r -> {
        Thread t = new Thread(r, "dom-text-timeout");
        t.setDaemon(true);
        return t;
    });

    /** UIA 는 최대 3.5초 걸린다 — WS 수신 스레드에서 부르면 그동안 다른 메시지가 밀린다. */
    private final ExecutorService fallbackExecutor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "dom-text-fallback");
        t.setDaemon(true);
        return t;
    });

    public DomTextService(ExtHub extHub, AgentHub agentHub, FeHub feHub,
                          BrowserTextService browserTextService) {
        this.extHub = extHub;
        this.agentHub = agentHub;
        this.feHub = feHub;
        this.browserTextService = browserTextService;
    }

    /** AI 의 dom_text_request 처리. */
    public void request() {
        if (!extHub.connected()) {
            fallbackExecutor.execute(this::readViaAccessibility);
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
            unavailable(d.path("reason").asText("본문을 추출하지 못했습니다"), VIA_EXTENSION);
            return;
        }
        String text = d.path("text").asText("");
        boolean truncated = d.path("truncated").asBoolean(false);
        if (text.length() > MAX_TEXT_CHARS) {
            text = text.substring(0, MAX_TEXT_CHARS);
            truncated = true;
        }
        available(VIA_EXTENSION, d.path("url").asText(null), d.path("title").asText(null), text, truncated);
    }

    /** 확장이 없을 때의 공급원 — 화면 접근성으로 브라우저 창을 직접 읽는다. */
    private void readViaAccessibility() {
        BrowserTextService.Read read;
        try {
            read = browserTextService.read();
        } catch (Exception e) {
            log.warn("접근성 폴백이 예외로 끝났습니다", e);
            read = new BrowserTextService.Read(null, "브라우저에서 본문을 읽지 못했습니다");
        }
        noticeExtensionMissing(read.ok());
        if (!read.ok()) {
            unavailable(read.reason(), VIA_ACCESSIBILITY);
            return;
        }
        BrowserTextService.Page page = read.page();
        available(VIA_ACCESSIBILITY, page.url(), page.title(), page.text(), page.truncated());
    }

    /** 사용자에게 확장 부재를 알리는 FE 팝업. 잦은 재호출에는 한 번만 띄운다. */
    private void noticeExtensionMissing(boolean gotText) {
        long now = System.currentTimeMillis();
        long previous = lastNoticeAt.get();
        if (now - previous < NOTICE_INTERVAL_MS || !lastNoticeAt.compareAndSet(previous, now)) {
            return;
        }
        String message = gotText
                ? "브라우저 확장이 설치되어 있지 않아 화면 읽기로 내용을 가져왔습니다. 일부가 빠지거나 섞일 수 있어요."
                : "브라우저 확장이 설치되어 있지 않아 페이지 내용을 가져오지 못했습니다.";
        feHub.send("notice", Map.of("message", message));
    }

    private void expire(String requestId) {
        if (pending.remove(requestId) != null) {
            unavailable("브라우저 확장이 응답하지 않습니다", VIA_EXTENSION);
        }
    }

    private void available(String via, String url, String title, String text, boolean truncated) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("available", true);
        body.put("via", via);
        body.put("url", url);
        body.put("title", title);
        body.put("text", text);
        body.put("truncated", truncated);
        agentHub.send("dom_text", body);
    }

    private void unavailable(String reason, String via) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("available", false);
        body.put("via", via);
        body.put("reason", reason);
        agentHub.send("dom_text", body);
    }

    @PreDestroy
    void shutdown() {
        scheduler.shutdownNow();
        fallbackExecutor.shutdownNow();
    }
}
