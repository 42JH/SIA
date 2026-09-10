package com.sia.assistant.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class SharedTokenFilterTest {

    private SharedTokenFilter filter;

    @BeforeEach
    void setUp() {
        RuntimeTokenManager tokens = mock(RuntimeTokenManager.class);
        when(tokens.token()).thenReturn("secret-token");
        filter = new SharedTokenFilter(tokens);
    }

    private MockHttpServletRequest mcpRequest() {
        return new MockHttpServletRequest("POST", "/mcp/messages");
    }

    @Test
    @DisplayName("토큰 없는 /mcp 요청은 401 JSON 으로 끊긴다")
    void missingTokenIsRejected() throws Exception {
        MockHttpServletResponse response = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(mcpRequest(), response, chain);

        assertThat(chain.getRequest()).isNull();
        assertThat(response.getStatus()).isEqualTo(401);
        assertThat(response.getContentAsString()).contains("UNAUTHORIZED");
    }

    @Test
    @DisplayName("Authorization: Bearer 토큰이 맞으면 통과한다")
    void bearerTokenPasses() throws Exception {
        MockHttpServletRequest request = mcpRequest();
        request.addHeader("Authorization", "Bearer secret-token");
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(request, new MockHttpServletResponse(), chain);

        assertThat(chain.getRequest()).isNotNull();
    }

    @Test
    @DisplayName("X-MC-Token 헤더로도 통과할 수 있다")
    void directHeaderPasses() throws Exception {
        MockHttpServletRequest request = mcpRequest();
        request.addHeader("X-MC-Token", "secret-token");
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(request, new MockHttpServletResponse(), chain);

        assertThat(chain.getRequest()).isNotNull();
    }

    @Test
    @DisplayName("틀린 토큰은 401 이다")
    void wrongTokenIsRejected() throws Exception {
        MockHttpServletRequest request = mcpRequest();
        request.addHeader("Authorization", "Bearer wrong-token");
        MockHttpServletResponse response = new MockHttpServletResponse();
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(request, response, chain);

        assertThat(chain.getRequest()).isNull();
        assertThat(response.getStatus()).isEqualTo(401);
    }

    @Test
    @DisplayName("/mcp 밖의 경로는 토큰 없이도 필터를 지나간다")
    void nonMcpPathSkipsCheck() throws Exception {
        MockFilterChain chain = new MockFilterChain();

        filter.doFilter(new MockHttpServletRequest("GET", "/api/status"),
                new MockHttpServletResponse(), chain);

        assertThat(chain.getRequest()).isNotNull();
    }
}
