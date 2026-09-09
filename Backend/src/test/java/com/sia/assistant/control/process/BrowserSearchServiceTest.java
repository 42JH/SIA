package com.sia.assistant.control.process;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.ws.ExtHub;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import tools.jackson.databind.ObjectMapper;

/**
 * browser.search 의 두 갈래 — 검색어/주소 판정(toUrl)과 확장 연결 여부에 따른 경로 선택.
 * OS 경로는 실제로 브라우저를 띄우므로 여기서 확인하는 것은 확장 경로와 폴백 판단까지다.
 */
class BrowserSearchServiceTest {

    private static final ObjectMapper OM = new ObjectMapper();

    @Test
    @DisplayName("http(s) 로 시작하면 그 주소를 그대로 연다")
    void webSchemePassesThrough() {
        assertThat(BrowserSearchService.toUrl("https://news.example.com/a/1"))
                .isEqualTo("https://news.example.com/a/1");
        assertThat(BrowserSearchService.toUrl("  http://example.com  "))
                .isEqualTo("http://example.com");
    }

    @Test
    @DisplayName("주소가 아니면 전부 검색어다 — 스킴 없는 도메인도 포함")
    void everythingElseIsAQuery() {
        assertThat(BrowserSearchService.toUrl("반도체 수출"))
                .isEqualTo("https://www.google.com/search?q=%EB%B0%98%EB%8F%84%EC%B2%B4+%EC%88%98%EC%B6%9C");
        // 검색 엔진이 알아서 주소로 안내한다 — BE 가 스킴을 붙여 주지 않는다
        assertThat(BrowserSearchService.toUrl("www.naver.com"))
                .isEqualTo("https://www.google.com/search?q=www.naver.com");
        // 콜론이 들어간 평범한 검색어까지 막지는 않는다
        assertThat(BrowserSearchService.toUrl("회의 9:30 정리"))
                .startsWith("https://www.google.com/search?q=");
    }

    @Test
    @DisplayName("로컬 파일·스크립트 스킴은 검색어로도 넘기지 않고 INVALID_REQUEST 로 막는다")
    void blockedSchemesAreRejected() {
        for (String bad : new String[] {
                "file:///C:/Users/SSAFY/secret.txt", "javascript:alert(1)",
                "data:text/html,<script>1</script>", "chrome://settings", "ftp://example.com/x"}) {
            assertThatThrownBy(() -> BrowserSearchService.toUrl(bad))
                    .isInstanceOf(ApiException.class)
                    .satisfies(e -> assertThat(((ApiException) e).code).isEqualTo(ErrorCode.INVALID_REQUEST));
        }
    }

    @Test
    @DisplayName("빈 query 와 host 없는 http 주소는 INVALID_REQUEST 다")
    void emptyAndMalformedAreRejected() {
        assertThatThrownBy(() -> BrowserSearchService.toUrl("   "))
                .isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> BrowserSearchService.toUrl(null))
                .isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> BrowserSearchService.toUrl("https:// 빈 호스트"))
                .isInstanceOf(ApiException.class);
    }

    @Test
    @DisplayName("확장이 연결돼 있으면 browser_open_request 를 보내고 via=extension 으로 답한다")
    void extensionPathOpensTab() throws Exception {
        ExtHub extHub = mock(ExtHub.class);
        when(extHub.connected()).thenReturn(true);
        BrowserSearchService service = new BrowserSearchService(extHub);

        // 확장 응답은 다른 스레드(WS 수신)로 들어온다 — 요청이 나간 뒤 requestId 를 집어 회신한다
        CompletableFuture<Map<String, Object>> result = CompletableFuture.supplyAsync(
                () -> service.search("반도체 수출"));

        ArgumentCaptor<Map<String, Object>> sent = captureSend(extHub);
        String requestId = String.valueOf(sent.getValue().get("requestId"));
        assertThat(sent.getValue().get("url")).asString().startsWith("https://www.google.com/search?q=");

        service.onReply(OM.readTree("{\"requestId\":\"" + requestId
                + "\",\"ok\":true,\"url\":\"https://www.google.com/search?q=x\","
                + "\"title\":\"반도체 수출 - Google 검색\",\"tabId\":42}"));

        Map<String, Object> out = result.get(3, TimeUnit.SECONDS);
        assertThat(out).containsEntry("ok", true)
                .containsEntry("via", "extension")
                .containsEntry("title", "반도체 수출 - Google 검색")
                .containsEntry("tabId", 42)
                // 같은 브라우저 안이라 이어서 dom_text 로 본문을 읽을 수 있다
                .containsEntry("domAvailable", true);
    }

    @Test
    @DisplayName("막힌 스킴은 경로가 갈리기 전에 끊긴다 — 확장에도 OS 에도 넘어가지 않는다")
    void blockedSchemeNeverReachesEitherPath() {
        ExtHub extHub = mock(ExtHub.class);
        BrowserSearchService service = new BrowserSearchService(extHub);

        assertThatThrownBy(() -> service.search("file:///C:/Users/SSAFY/secret.txt"))
                .isInstanceOf(ApiException.class);
        // connected() 조회조차 하지 않는다 — URL 판정이 경로 선택보다 먼저다
        verifyNoInteractions(extHub);
    }

    @Test
    @DisplayName("모르는 requestId 의 응답은 조용히 버린다 — 타임아웃 뒤 늦게 온 회신")
    void staleReplyIsIgnored() throws Exception {
        ExtHub extHub = mock(ExtHub.class);
        BrowserSearchService service = new BrowserSearchService(extHub);

        service.onReply(OM.readTree("{\"requestId\":\"deadbeef\",\"ok\":true}"));
        // 예외 없이 지나가면 된다
    }

    @SuppressWarnings("unchecked")
    private static ArgumentCaptor<Map<String, Object>> captureSend(ExtHub extHub) {
        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(extHub, org.mockito.Mockito.timeout(3000))
                .send(org.mockito.ArgumentMatchers.eq("browser_open_request"), captor.capture());
        return captor;
    }
}
