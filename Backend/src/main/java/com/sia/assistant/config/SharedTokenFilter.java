package com.sia.assistant.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * /mcp 로 시작하는 요청만 공유 토큰을 검사한다.
 * 헤더: Authorization: Bearer <token> 또는 X-MC-Token: <token>.
 * 역할은 같은 PC 의 다른 프로세스가 실수로 MCP 를 부르는 것을 막는 문턱이고,
 * 원격 방어는 루프백 바인딩의 몫이다.
 */
@Component
public class SharedTokenFilter extends OncePerRequestFilter {

    private final RuntimeTokenManager tokens;

    public SharedTokenFilter(RuntimeTokenManager tokens) {
        this.tokens = tokens;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !request.getRequestURI().startsWith("/mcp");
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String presented = extract(request);
        if (presented != null && constantTimeEquals(presented, tokens.token())) {
            chain.doFilter(request, response);
            return;
        }
        response.setStatus(401);
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write("{\"code\":\"UNAUTHORIZED\",\"message\":\"MCP 토큰이 필요합니다\"}");
    }

    private String extract(HttpServletRequest request) {
        String auth = request.getHeader("Authorization");
        if (auth != null && auth.startsWith("Bearer ")) {
            return auth.substring("Bearer ".length()).trim();
        }
        String direct = request.getHeader("X-MC-Token");
        return direct == null ? null : direct.trim();
    }

    private boolean constantTimeEquals(String a, String b) {
        return MessageDigest.isEqual(a.getBytes(StandardCharsets.UTF_8), b.getBytes(StandardCharsets.UTF_8));
    }
}
