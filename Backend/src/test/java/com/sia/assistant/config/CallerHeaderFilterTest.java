package com.sia.assistant.config;

import static org.assertj.core.api.Assertions.assertThat;

import com.sia.assistant.mcp.Caller;
import com.sia.assistant.mcp.CallerContext;
import jakarta.servlet.FilterChain;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class CallerHeaderFilterTest {

    private final CallerHeaderFilter filter = new CallerHeaderFilter();

    @AfterEach
    void tearDown() {
        CallerContext.clear();
    }

    private Caller callerSeenInChain(MockHttpServletRequest request) throws Exception {
        AtomicReference<Caller> seen = new AtomicReference<>();
        FilterChain chain = (req, res) -> seen.set(CallerContext.get());
        filter.doFilter(request, new MockHttpServletResponse(), chain);
        return seen.get();
    }

    @Test
    @DisplayName("X-Caller: GESTURE 는 대소문자 무관하게 GESTURE 로 잡힌다")
    void gestureHeaderSetsGestureCaller() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/mcp/messages");
        request.addHeader("X-Caller", "gesture");

        assertThat(callerSeenInChain(request)).isEqualTo(Caller.GESTURE);
    }

    @Test
    @DisplayName("헤더가 없거나 모르는 값이면 LLM 이 기본이다")
    void unknownHeaderDefaultsToLlm() throws Exception {
        assertThat(callerSeenInChain(new MockHttpServletRequest("POST", "/mcp/messages")))
                .isEqualTo(Caller.LLM);

        MockHttpServletRequest weird = new MockHttpServletRequest("POST", "/mcp/messages");
        weird.addHeader("X-Caller", "ROBOT");
        assertThat(callerSeenInChain(weird)).isEqualTo(Caller.LLM);
    }

    @Test
    @DisplayName("요청이 끝나면 ThreadLocal 은 반드시 청소된다")
    void contextIsClearedAfterRequest() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/mcp/messages");
        request.addHeader("X-Caller", "GESTURE");

        callerSeenInChain(request);

        assertThat(CallerContext.get()).isEqualTo(Caller.LLM);
    }

    @Test
    @DisplayName("경로를 가리지 않는다 — 인코딩 표기(/%6dcp)에서도 X-Caller 가 살아 있다")
    void pathIsNotJudged() throws Exception {
        // 예전엔 getRequestURI().startsWith("/mcp") 로 범위를 좁혔는데, 그 값은 디코딩 전이라
        // /%6dcp 로 오면 헤더가 조용히 무시돼 GESTURE 호출이 LLM 으로 기록됐다.
        MockHttpServletRequest encoded = new MockHttpServletRequest("POST", "/%6dcp");
        encoded.addHeader("X-Caller", "GESTURE");
        assertThat(callerSeenInChain(encoded)).isEqualTo(Caller.GESTURE);

        // MCP 밖에서 설정돼도 무해하다 — 이 ThreadLocal 은 도구 실행부만 읽고 finally 가 지운다
        MockHttpServletRequest other = new MockHttpServletRequest("GET", "/api/status");
        other.addHeader("X-Caller", "GESTURE");
        assertThat(callerSeenInChain(other)).isEqualTo(Caller.GESTURE);
        assertThat(CallerContext.get()).isEqualTo(Caller.LLM);
    }
}
