package com.sia.assistant.domtext;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sia.assistant.common.ApiException;
import com.sia.assistant.control.browser.BrowserTextService;
import com.sia.assistant.ws.ExtHub;
import com.sia.assistant.ws.FeHub;
import java.util.Map;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

/**
 * browser.dom_text 의 공급원 갈림 — 확장이 붙어 있으면 /ws/ext 로 중계하고, 없으면 접근성으로 직접 읽는다.
 * 어느 쪽이든 AI 는 via 로 출처를 알고, 접근성 경로에서는 사용자에게 FE 팝업이 한 번 뜬다.
 * 읽지 못하면 빈 결과가 아니라 예외다 — ToolGate 가 FAILED 로 기록하고 isError 로 되돌린다.
 */
class DomTextServiceTest {

    private static final ObjectMapper OM = new ObjectMapper();

    private ExtHub extHub;
    private FeHub feHub;
    private BrowserTextService browserTextService;
    private DomTextService service;

    @BeforeEach
    void setUp() {
        extHub = mock(ExtHub.class);
        feHub = mock(FeHub.class);
        browserTextService = mock(BrowserTextService.class);
        service = new DomTextService(extHub, feHub, browserTextService);
    }

    @Test
    @DisplayName("확장이 붙어 있으면 확장에 중계하고 접근성은 건드리지 않는다")
    void extensionPathRelays() throws Exception {
        when(extHub.connected()).thenReturn(true);

        // 확장 응답은 다른 스레드(WS 수신)로 들어온다 — 요청이 나간 뒤 requestId 를 집어 회신한다
        CompletableFuture<Map<String, Object>> result = CompletableFuture.supplyAsync(service::read);

        ArgumentCaptor<Map<String, Object>> sent = captor();
        verify(extHub, timeout(3000)).send(eq("dom_text_request"), sent.capture());
        String requestId = String.valueOf(sent.getValue().get("requestId"));

        service.onReply(OM.readTree("{\"requestId\":\"" + requestId
                + "\",\"available\":true,\"url\":\"https://news.example.com/a/1\","
                + "\"title\":\"제목\",\"text\":\"본문\",\"truncated\":false}"));

        assertThat(result.get(3, TimeUnit.SECONDS))
                .containsEntry("via", "extension")
                .containsEntry("url", "https://news.example.com/a/1")
                .containsEntry("title", "제목")
                .containsEntry("text", "본문")
                .containsEntry("truncated", false);

        verify(browserTextService, never()).read();
        verify(feHub, never()).send(eq("notice"), any());
    }

    @Test
    @DisplayName("확장이 본문 없음을 보고하면 접근성으로 넘어가지 않고 그대로 실패다")
    void extensionUnavailableFails() throws Exception {
        when(extHub.connected()).thenReturn(true);

        CompletableFuture<Map<String, Object>> result = CompletableFuture.supplyAsync(service::read);

        ArgumentCaptor<Map<String, Object>> sent = captor();
        verify(extHub, timeout(3000)).send(eq("dom_text_request"), sent.capture());
        service.onReply(OM.readTree("{\"requestId\":\"" + sent.getValue().get("requestId")
                + "\",\"available\":false,\"reason\":\"이 페이지는 읽을 수 없습니다\"}"));

        assertThatThrownBy(() -> result.get(3, TimeUnit.SECONDS))
                .cause().isInstanceOf(ApiException.class)
                .hasMessage("이 페이지는 읽을 수 없습니다");
        verify(browserTextService, never()).read();
    }

    @Test
    @DisplayName("모르는 requestId 의 응답은 조용히 버린다 — 타임아웃 뒤 늦게 온 회신")
    void unknownReplyIgnored() throws Exception {
        service.onReply(OM.readTree("{\"requestId\":\"deadbeef\",\"available\":true,\"text\":\"x\"}"));
        // 아무도 기다리지 않으므로 예외 없이 지나가면 된다
    }

    @Test
    @DisplayName("확장이 없으면 접근성으로 읽어 via=accessibility 로 답하고 FE 팝업을 띄운다")
    void fallbackReadsViaAccessibility() {
        when(extHub.connected()).thenReturn(false);
        when(browserTextService.read()).thenReturn(new BrowserTextService.Read(
                new BrowserTextService.Page("https://news.example.com/a/1", "제목", "본문", false), null));

        assertThat(service.read())
                .containsEntry("via", "accessibility")
                .containsEntry("url", "https://news.example.com/a/1")
                .containsEntry("title", "제목")
                .containsEntry("text", "본문")
                .containsEntry("truncated", false);

        // 사용자에게는 확장이 없다는 사실이 팝업으로 뜬다
        ArgumentCaptor<Map<String, Object>> notice = captor();
        verify(feHub).send(eq("notice"), notice.capture());
        assertThat(String.valueOf(notice.getValue().get("message"))).contains("브라우저 확장이 설치되어 있지 않아");
    }

    @Test
    @DisplayName("접근성으로도 못 읽으면 reason 을 그대로 실어 실패하고 실패 문구로 팝업을 띄운다")
    void fallbackFailureKeepsReason() {
        when(extHub.connected()).thenReturn(false);
        when(browserTextService.read())
                .thenReturn(new BrowserTextService.Read(null, "열려 있는 브라우저 창을 찾지 못했습니다"));

        assertThatThrownBy(() -> service.read())
                .isInstanceOf(ApiException.class)
                .hasMessage("열려 있는 브라우저 창을 찾지 못했습니다");

        // 실패해도 확장이 없다는 사실은 알린다 — 문구만 다르다
        ArgumentCaptor<Map<String, Object>> notice = captor();
        verify(feHub).send(eq("notice"), notice.capture());
        assertThat(String.valueOf(notice.getValue().get("message"))).contains("가져오지 못했습니다");
    }

    @Test
    @DisplayName("접근성 폴백이 예외로 끝나도 도구 실패로 정리된다 — 날 예외가 새지 않는다")
    void fallbackExceptionBecomesApiException() {
        when(extHub.connected()).thenReturn(false);
        when(browserTextService.read()).thenThrow(new IllegalStateException("UIA 폭발"));

        assertThatThrownBy(() -> service.read())
                .isInstanceOf(ApiException.class)
                .hasMessage("브라우저에서 본문을 읽지 못했습니다");
    }

    @Test
    @DisplayName("연달아 불러도 팝업은 한 번만 뜬다 — 한 발화가 이 도구를 여러 번 부를 수 있다")
    void noticeIsThrottled() {
        when(extHub.connected()).thenReturn(false);
        when(browserTextService.read()).thenReturn(new BrowserTextService.Read(
                new BrowserTextService.Page(null, "제목", "본문", false), null));

        service.read();
        service.read();
        service.read();

        // 본문은 매번 돌아가지만 팝업은 60초에 한 번이다
        verify(browserTextService, timeout(3000).times(3)).read();
        verify(feHub, timeout(3000).times(1)).send(eq("notice"), any());
    }

    @SuppressWarnings("unchecked")
    private static ArgumentCaptor<Map<String, Object>> captor() {
        return ArgumentCaptor.forClass(Map.class);
    }
}
