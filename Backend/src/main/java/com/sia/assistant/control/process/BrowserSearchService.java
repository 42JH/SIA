package com.sia.assistant.control.process;

import com.fasterxml.jackson.databind.JsonNode;
import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.ws.ExtHub;
import java.awt.Desktop;
import java.io.IOException;
import java.net.URI;
import java.net.URISyntaxException;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * browser.search 의 실행부. 여는 경로가 둘이고, 갈림은 브라우저 확장(/ws/ext) 연결 여부 하나다.
 *
 * <p>확장 연결 O — 확장에 {@code browser_open_request} 를 보내 활성 크롬 창에 새 탭으로 연다.
 * 같은 브라우저 안이라 이어서 {@code dom_text} 로 본문을 읽을 수 있다 ({@code domAvailable: true}).
 *
 * <p>확장 연결 X — OS 기본 브라우저로 연다. 열리기는 하지만 BE 에는 그 탭을 들여다볼 통로가 없다
 * ({@code domAvailable: false}). AI 는 이 값을 보고 "본문을 읽었다"고 말할지 판단한다.
 *
 * <p>★ 확장이 4초 안에 답하지 않거나 실패를 보고하면 OS 경로로 폴백한다 — "검색해줘"가 조용히 실패하는 것보다
 * 낫다. 폴백 뒤 늦게 도착한 확장 응답은 무시되므로 탭이 둘 열릴 수 있으나, 그 창은 이미 서비스 워커가
 * 죽었거나 막힌 상태라 실제로는 열리지 않는다.
 *
 * <p>★ LLM 이 임의 스킴을 열 수 있는 칸은 없다 — {@code http(s)} 만 주소로 취급하고, 로컬 파일이나
 * 스크립트 스킴은 검색어로도 넘기지 않고 INVALID_REQUEST 로 되돌린다 (AppLaunchService 가 임의 경로 실행을
 * 막는 것과 같은 정신이다).
 */
@Service
public class BrowserSearchService {

    private static final Logger log = LoggerFactory.getLogger(BrowserSearchService.class);

    private static final String SEARCH_PREFIX = "https://www.google.com/search?q=";
    private static final long EXT_TIMEOUT_MS = 4000;
    private static final int MAX_QUERY_CHARS = 500;

    /** 주소로 열어 줄 수 있는 스킴은 이 둘뿐이다. */
    private static final Pattern WEB_SCHEME = Pattern.compile("^https?://", Pattern.CASE_INSENSITIVE);
    /** 검색어로도 넘기지 않고 막는 스킴 — 로컬 파일 · 스크립트 · 브라우저 내부 페이지. */
    private static final Pattern BLOCKED_SCHEME = Pattern.compile(
            "^(file|javascript|data|vbscript|about|blob|view-source|chrome|chrome-extension|edge|ms-[a-z-]+)\\s*:",
            Pattern.CASE_INSENSITIVE);

    private final ExtHub extHub;
    private final Map<String, CompletableFuture<JsonNode>> pending = new ConcurrentHashMap<>();

    public BrowserSearchService(ExtHub extHub) {
        this.extHub = extHub;
    }

    public Map<String, Object> search(String query) {
        String url = toUrl(query);
        if (extHub.connected()) {
            Map<String, Object> viaExtension = openWithExtension(url);
            if (viaExtension != null) {
                return viaExtension;
            }
            log.info("확장 경로가 실패해 OS 기본 브라우저로 폴백합니다");
        }
        return openWithOs(url);
    }

    /** 확장의 browser_open 응답 처리 — 기다리는 호출 스레드를 깨운다. */
    public void onReply(JsonNode d) {
        String requestId = d.path("requestId").asText("");
        CompletableFuture<JsonNode> waiting = pending.remove(requestId);
        if (waiting == null) {
            log.debug("만료되었거나 모르는 browser_open 응답 무시: {}", requestId);
            return;
        }
        waiting.complete(d);
    }

    /**
     * 검색어 · 주소를 실제로 열 URL 로 바꾼다.
     * http(s) 로 시작하면 그대로, 막힌 스킴이면 거절, 나머지는 전부 검색어다.
     */
    static String toUrl(String query) {
        String q = query == null ? "" : query.trim();
        if (q.isEmpty()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "검색어나 주소(query)가 필요합니다");
        }
        if (q.length() > MAX_QUERY_CHARS) {
            throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "검색어가 너무 깁니다 (" + MAX_QUERY_CHARS + "자 이하)");
        }
        if (WEB_SCHEME.matcher(q).find()) {
            try {
                URI uri = new URI(q);
                if (uri.getHost() == null || uri.getHost().isBlank()) {
                    throw new URISyntaxException(q, "host 가 없습니다");
                }
                return uri.toASCIIString();
            } catch (URISyntaxException e) {
                throw new ApiException(ErrorCode.INVALID_REQUEST,
                        "열 수 없는 주소입니다. 올바른 http(s) 주소이거나 검색어여야 합니다");
            }
        }
        if (BLOCKED_SCHEME.matcher(q).find() || q.contains("://")) {
            throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "http(s) 가 아닌 주소는 열 수 없습니다. 검색어를 넘기세요");
        }
        // "www.naver.com" 처럼 스킴 없는 문자열도 검색어다 — 검색 엔진이 알아서 주소로 안내한다
        return SEARCH_PREFIX + URLEncoder.encode(q, StandardCharsets.UTF_8);
    }

    /** 확장에 탭 열기를 맡기고 응답을 기다린다. 실패하면 null — 호출자가 OS 경로로 폴백한다. */
    private Map<String, Object> openWithExtension(String url) {
        String requestId = UUID.randomUUID().toString().substring(0, 8);
        CompletableFuture<JsonNode> waiting = new CompletableFuture<>();
        pending.put(requestId, waiting);
        try {
            Map<String, Object> request = new LinkedHashMap<>();
            request.put("requestId", requestId);
            request.put("url", url);
            extHub.send("browser_open_request", request);

            JsonNode d = waiting.get(EXT_TIMEOUT_MS, TimeUnit.MILLISECONDS);
            if (!d.path("ok").asBoolean(false)) {
                log.warn("확장이 탭 열기를 실패로 보고했습니다: {}", d.path("reason").asText("사유 없음"));
                return null;
            }
            String title = d.path("title").asText("");
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("ok", true);
            out.put("via", "extension");
            out.put("url", d.path("url").asText(url));
            out.put("title", title.isBlank() ? null : title);
            out.put("tabId", d.path("tabId").isNumber() ? d.path("tabId").asInt() : null);
            out.put("domAvailable", true);
            return out;
        } catch (TimeoutException e) {
            log.warn("확장이 {}ms 안에 browser_open 을 회신하지 않았습니다", EXT_TIMEOUT_MS);
            return null;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return null;
        } catch (ExecutionException e) {
            log.warn("확장 경로 처리에 실패했습니다", e);
            return null;
        } finally {
            pending.remove(requestId);
        }
    }

    /** OS 기본 브라우저로 연다. Desktop 이 없거나 실패하면 rundll32 로 한 번 더 시도한다. */
    private Map<String, Object> openWithOs(String url) {
        boolean opened = false;
        try {
            if (Desktop.isDesktopSupported() && Desktop.getDesktop().isSupported(Desktop.Action.BROWSE)) {
                Desktop.getDesktop().browse(URI.create(url));
                opened = true;
            }
        } catch (Exception e) {
            log.warn("Desktop.browse 실패 — rundll32 로 다시 시도합니다: {}", e.toString());
        }
        if (!opened) {
            try {
                new ProcessBuilder("rundll32", "url.dll,FileProtocolHandler", url).start();
            } catch (IOException e) {
                log.warn("기본 브라우저 실행 실패: {}", url, e);
                throw new ApiException(ErrorCode.INTERNAL_ERROR,
                        "브라우저를 열지 못했습니다. 잠시 후 다시 시도해주세요", e.getMessage());
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("ok", true);
        out.put("via", "os");
        out.put("url", url);
        out.put("domAvailable", false);
        return out;
    }
}
