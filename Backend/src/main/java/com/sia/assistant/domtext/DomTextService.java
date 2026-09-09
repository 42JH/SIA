package com.sia.assistant.domtext;

import com.fasterxml.jackson.databind.JsonNode;
import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.control.browser.BrowserTextService;
import com.sia.assistant.ws.ExtHub;
import com.sia.assistant.ws.FeHub;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.concurrent.atomic.AtomicLong;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * browser.dom_text 의 실행부 — 지금 보고 있는 페이지의 본문을 돌려준다. 공급원이 둘이다.
 *
 * <p><b>확장이 붙어 있으면</b> /ws/ext 로 중계한다 ({@code via: "extension"}). requestId 상관관계는
 * BE ↔ 확장 사이에서만 쓰고 도구 표면에는 나타나지 않는다. 무응답은 4초에 끊는다.
 *
 * <p><b>확장이 없으면</b> 화면 접근성(UIA)으로 브라우저 창을 직접 읽는다 ({@code via: "accessibility"}).
 * 본문만 골라내지 못해 메뉴·사이드바가 섞이므로 AI 가 품질을 알도록 via 를 싣고, 사용자에게는
 * FE 팝업(notice)으로 확장이 없다는 사실을 알린다.
 *
 * <p>★ notice 는 원래 AI 가 소유하는 채널이지만(AI → BE → FE) 이 한 건은 BE 가 직접 보낸다 —
 * 확장 부재는 대화가 아니라 시스템 상태이고, AI 가 언급을 생략해도 사용자는 알아야 하기 때문이다.
 * 프로토콜.md §6.6 에 예외로 적어 두었다.
 *
 * <p>★ 본문을 못 읽으면 빈 결과가 아니라 예외로 끝낸다. 도구의 실패 어휘는 {@code isError} 하나이고
 * (프로토콜.md §7.2), 그래야 tool_call 에도 FAILED 로 남아 확장 경로와 폴백 경로의 성적을 나중에 볼 수 있다.
 */
@Service
public class DomTextService {

    private static final Logger log = LoggerFactory.getLogger(DomTextService.class);

    private static final long TIMEOUT_MS = 4000;
    /** LLM 컨텍스트 보호 — 확장도 자르지만 서버에서 한 번 더 강제한다. */
    private static final int MAX_TEXT_CHARS = 20000;

    private static final String VIA_EXTENSION = "extension";
    private static final String VIA_ACCESSIBILITY = "accessibility";

    /** 같은 팝업이 연달아 뜨지 않게 하는 간격. 한 번의 발화가 이 도구를 여러 번 부를 수 있다. */
    private static final long NOTICE_INTERVAL_MS = 60_000;

    private final ExtHub extHub;
    private final FeHub feHub;
    private final BrowserTextService browserTextService;
    private final Map<String, CompletableFuture<JsonNode>> pending = new ConcurrentHashMap<>();
    private final AtomicLong lastNoticeAt = new AtomicLong(0);

    public DomTextService(ExtHub extHub, FeHub feHub, BrowserTextService browserTextService) {
        this.extHub = extHub;
        this.feHub = feHub;
        this.browserTextService = browserTextService;
    }

    /**
     * 활성 페이지의 본문을 읽는다. 호출 스레드를 최대 {@value #TIMEOUT_MS}ms 붙잡는다 —
     * MCP 요청 스레드에서 불리므로 블로킹해도 다른 채널이 밀리지 않는다.
     */
    public Map<String, Object> read() {
        return extHub.connected() ? readViaExtension() : readViaAccessibility();
    }

    /** 확장의 dom_text 응답 처리 — 기다리는 호출 스레드를 깨운다. */
    public void onReply(JsonNode d) {
        String requestId = d.path("requestId").asText("");
        CompletableFuture<JsonNode> waiting = pending.remove(requestId);
        if (waiting == null) {
            log.debug("만료되었거나 모르는 dom_text 응답 무시: {}", requestId);
            return;
        }
        waiting.complete(d);
    }

    /** 1순위 공급원 — 확장이 활성 탭에서 본문을 뽑아 준다. */
    private Map<String, Object> readViaExtension() {
        String requestId = UUID.randomUUID().toString().substring(0, 8);
        CompletableFuture<JsonNode> waiting = new CompletableFuture<>();
        pending.put(requestId, waiting);
        try {
            extHub.send("dom_text_request", Map.of("requestId", requestId));
            JsonNode d = waiting.get(TIMEOUT_MS, TimeUnit.MILLISECONDS);

            if (!d.path("available").asBoolean(false)) {
                throw unavailable(d.path("reason").asText("본문을 추출하지 못했습니다"));
            }
            String text = d.path("text").asText("");
            boolean truncated = d.path("truncated").asBoolean(false);
            if (text.length() > MAX_TEXT_CHARS) {
                text = text.substring(0, MAX_TEXT_CHARS);
                truncated = true;
            }
            return page(VIA_EXTENSION, d.path("url").asText(null), d.path("title").asText(null), text, truncated);

        } catch (TimeoutException e) {
            log.warn("확장이 {}ms 안에 dom_text 를 회신하지 않았습니다", TIMEOUT_MS);
            throw unavailable("브라우저 확장이 응답하지 않습니다");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw unavailable("본문을 읽는 중 중단되었습니다");
        } catch (ExecutionException e) {
            log.warn("확장 경로 처리에 실패했습니다", e);
            throw unavailable("브라우저에서 본문을 읽지 못했습니다");
        } finally {
            pending.remove(requestId);
        }
    }

    /** 확장이 없을 때의 공급원 — 화면 접근성으로 브라우저 창을 직접 읽는다. */
    private Map<String, Object> readViaAccessibility() {
        BrowserTextService.Read read;
        try {
            read = browserTextService.read();
        } catch (Exception e) {
            log.warn("접근성 폴백이 예외로 끝났습니다", e);
            read = new BrowserTextService.Read(null, "브라우저에서 본문을 읽지 못했습니다");
        }
        noticeExtensionMissing(read.ok());
        if (!read.ok()) {
            throw unavailable(read.reason());
        }
        BrowserTextService.Page page = read.page();
        return page(VIA_ACCESSIBILITY, page.url(), page.title(), page.text(), page.truncated());
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

    private static Map<String, Object> page(String via, String url, String title, String text, boolean truncated) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("via", via);
        body.put("url", url);
        body.put("title", title);
        body.put("text", text);
        body.put("truncated", truncated);
        return body;
    }

    /** ToolGate 가 FAILED 로 기록하고 LLM 에는 이 문장이 그대로 간다 (§7.2 의 8개 code 는 늘리지 않는다). */
    private static ApiException unavailable(String reason) {
        return new ApiException(ErrorCode.EXTENSION_UNAVAILABLE, reason);
    }
}
