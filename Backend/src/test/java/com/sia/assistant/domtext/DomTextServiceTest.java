package com.sia.assistant.domtext;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.sia.assistant.control.browser.BrowserTextService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.ExtHub;
import com.sia.assistant.ws.FeHub;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

/**
 * dom_text 의 공급원 갈림 — 확장이 붙어 있으면 /ws/ext 로 중계하고, 없으면 접근성으로 직접 읽는다.
 * 어느 쪽이든 AI 는 via 로 출처를 알고, 접근성 경로에서는 사용자에게 FE 팝업이 한 번 뜬다.
 */
class DomTextServiceTest {

    private ExtHub extHub;
    private AgentHub agentHub;
    private FeHub feHub;
    private BrowserTextService browserTextService;
    private DomTextService service;

    @BeforeEach
    void setUp() {
        extHub = mock(ExtHub.class);
        agentHub = mock(AgentHub.class);
        feHub = mock(FeHub.class);
        browserTextService = mock(BrowserTextService.class);
        service = new DomTextService(extHub, agentHub, feHub, browserTextService);
    }

    @Test
    @DisplayName("확장이 붙어 있으면 확장에 중계하고 접근성은 건드리지 않는다")
    void extensionPathRelays() {
        when(extHub.connected()).thenReturn(true);

        service.request();

        verify(extHub).send(eq("dom_text_request"), any());
        verify(browserTextService, never()).read();
        verify(feHub, never()).send(eq("notice"), any());
    }

    @Test
    @DisplayName("확장이 없으면 접근성으로 읽어 via=accessibility 로 답하고 FE 팝업을 띄운다")
    void fallbackReadsViaAccessibility() {
        when(extHub.connected()).thenReturn(false);
        when(browserTextService.read()).thenReturn(new BrowserTextService.Read(
                new BrowserTextService.Page("https://news.example.com/a/1", "제목", "본문", false), null));

        service.request();

        Map<String, Object> body = captureAgentSend();
        assertThat(body).containsEntry("available", true)
                .containsEntry("via", "accessibility")
                .containsEntry("url", "https://news.example.com/a/1")
                .containsEntry("title", "제목")
                .containsEntry("text", "본문")
                .containsEntry("truncated", false);

        // 사용자에게는 확장이 없다는 사실이 팝업으로 뜬다
        ArgumentCaptor<Map<String, Object>> notice = captor();
        verify(feHub, timeout(3000)).send(eq("notice"), notice.capture());
        assertThat(String.valueOf(notice.getValue().get("message"))).contains("브라우저 확장이 설치되어 있지 않아");
    }

    @Test
    @DisplayName("접근성으로도 못 읽으면 reason 을 그대로 싣고 실패 문구로 팝업을 띄운다")
    void fallbackFailureKeepsReason() {
        when(extHub.connected()).thenReturn(false);
        when(browserTextService.read())
                .thenReturn(new BrowserTextService.Read(null, "열려 있는 브라우저 창을 찾지 못했습니다"));

        service.request();

        Map<String, Object> body = captureAgentSend();
        assertThat(body).containsEntry("available", false)
                .containsEntry("via", "accessibility")
                .containsEntry("reason", "열려 있는 브라우저 창을 찾지 못했습니다");
        // 실패해도 확장이 없다는 사실은 알린다 — 문구만 다르다
        ArgumentCaptor<Map<String, Object>> notice = captor();
        verify(feHub, timeout(3000)).send(eq("notice"), notice.capture());
        assertThat(String.valueOf(notice.getValue().get("message"))).contains("가져오지 못했습니다");
    }

    @Test
    @DisplayName("접근성 폴백이 예외로 끝나도 AI 에는 반드시 답이 간다")
    void fallbackExceptionStillAnswers() {
        when(extHub.connected()).thenReturn(false);
        when(browserTextService.read()).thenThrow(new IllegalStateException("UIA 폭발"));

        service.request();

        assertThat(captureAgentSend()).containsEntry("available", false)
                .containsEntry("via", "accessibility");
    }

    @Test
    @DisplayName("연달아 불러도 팝업은 한 번만 뜬다 — 한 발화가 dom_text 를 여러 번 부를 수 있다")
    void noticeIsThrottled() {
        when(extHub.connected()).thenReturn(false);
        when(browserTextService.read()).thenReturn(new BrowserTextService.Read(
                new BrowserTextService.Page(null, "제목", "본문", false), null));

        service.request();
        captureAgentSend();
        service.request();
        service.request();

        // dom_text 는 매번 가지만 팝업은 60초에 한 번이다
        verify(agentHub, timeout(3000).atLeast(2)).send(eq("dom_text"), any());
        verify(feHub, timeout(3000).times(1)).send(eq("notice"), any());
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> captureAgentSend() {
        ArgumentCaptor<Map<String, Object>> captor = captor();
        verify(agentHub, timeout(3000)).send(eq("dom_text"), captor.capture());
        return captor.getValue();
    }

    @SuppressWarnings("unchecked")
    private static ArgumentCaptor<Map<String, Object>> captor() {
        return ArgumentCaptor.forClass(Map.class);
    }
}
