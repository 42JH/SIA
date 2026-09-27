package com.sia.assistant.config;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;

/**
 * 이 필터의 계약은 "토큰이 맞으면 ROLE_MCP 인증을 심는다" 하나다.
 * 막는 일(401)은 SecurityConfig 의 authorizeHttpRequests 몫이고, 그쪽은 SecurityBoundaryTest 가 본다.
 */
class SharedTokenFilterTest {

    private SharedTokenFilter filter;

    @BeforeEach
    void setUp() {
        RuntimeTokenManager tokens = mock(RuntimeTokenManager.class);
        when(tokens.token()).thenReturn("secret-token");
        filter = new SharedTokenFilter(tokens);
    }

    @AfterEach
    void tearDown() {
        SecurityContextHolder.clearContext();
    }

    private Authentication authAfter(MockHttpServletRequest request) throws Exception {
        MockFilterChain chain = new MockFilterChain();
        filter.doFilter(request, new MockHttpServletResponse(), chain);
        assertThat(chain.getRequest()).as("이 필터는 요청을 끊지 않는다").isNotNull();
        return SecurityContextHolder.getContext().getAuthentication();
    }

    @Test
    @DisplayName("Authorization: Bearer 토큰이 맞으면 ROLE_MCP 인증이 심긴다")
    void bearerTokenAuthenticates() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/mcp");
        request.addHeader("Authorization", "Bearer secret-token");

        Authentication auth = authAfter(request);

        assertThat(auth).isNotNull();
        assertThat(auth.isAuthenticated()).isTrue();
        assertThat(auth.getAuthorities()).extracting(Object::toString).containsExactly("ROLE_MCP");
    }

    @Test
    @DisplayName("X-MC-Token 헤더로도 인증된다")
    void directHeaderAuthenticates() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("POST", "/mcp");
        request.addHeader("X-MC-Token", "secret-token");

        assertThat(authAfter(request)).isNotNull();
    }

    @Test
    @DisplayName("토큰이 없거나 틀리면 인증을 심지 않고 그대로 흘려보낸다 — 막는 건 인가의 몫이다")
    void missingOrWrongTokenLeavesAnonymous() throws Exception {
        assertThat(authAfter(new MockHttpServletRequest("POST", "/mcp"))).isNull();

        MockHttpServletRequest wrong = new MockHttpServletRequest("POST", "/mcp");
        wrong.addHeader("Authorization", "Bearer wrong-token");
        assertThat(authAfter(wrong)).isNull();
    }

    @Test
    @DisplayName("경로를 보지 않는다 — 인코딩 표기(/%6dcp)든 /api 든 토큰만 본다")
    void pathIsNotJudged() throws Exception {
        MockHttpServletRequest encoded = new MockHttpServletRequest("POST", "/%6dcp");
        encoded.addHeader("Authorization", "Bearer secret-token");

        assertThat(authAfter(encoded)).isNotNull();
    }
}
