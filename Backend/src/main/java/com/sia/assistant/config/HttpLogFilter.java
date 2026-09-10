package com.sia.assistant.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * 들어오는 HTTP 요청 한 건을 콘솔 한 줄로 — {@code [http] METHOD URI -> status (ms)}.
 * /api/** (FE·AI 의 REST) 와 /mcp/** (LLM 도구 호출 전송) 가 대상이고, /mcp 는 X-Caller 도 함께 적는다.
 *
 * <p>가장 앞 순서로 둔다 — 그래야 {@link SharedTokenFilter} 가 401 로 끊은 요청도 한 줄 남는다.
 * 스웨거·정적 리소스·CORS 프리플라이트(OPTIONS)는 DEBUG 로 내린다 (통신 이벤트가 아니라 브라우저 잡음이다).
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class HttpLogFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(HttpLogFilter.class);

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        long t0 = System.currentTimeMillis();
        try {
            chain.doFilter(request, response);
        } finally {
            long ms = System.currentTimeMillis() - t0;
            String line = describe(request, response, ms);
            if (loud(request)) {
                log.info(line);
            } else {
                log.debug(line);
            }
        }
    }

    /** /api·/mcp 의 GET/POST/... 만 INFO. 그 밖(스웨거·정적 파일)과 OPTIONS 프리플라이트는 DEBUG. */
    static boolean loud(HttpServletRequest request) {
        if ("OPTIONS".equalsIgnoreCase(request.getMethod())) {
            return false;
        }
        String uri = request.getRequestURI();
        return uri.startsWith("/api") || uri.startsWith("/mcp");
    }

    static String describe(HttpServletRequest request, HttpServletResponse response, long ms) {
        StringBuilder sb = new StringBuilder(96);
        sb.append("[http] ").append(request.getMethod()).append(' ').append(request.getRequestURI());
        String query = request.getQueryString();
        if (query != null && !query.isEmpty()) {
            sb.append('?').append(query);
        }
        if (request.getRequestURI().startsWith("/mcp")) {
            String caller = request.getHeader("X-Caller");
            sb.append(" caller=").append(caller == null ? "LLM" : caller);
        }
        sb.append(" -> ");
        // MCP streamable 전송은 응답을 비동기로 이어 가므로 상태가 아직 정해지지 않았을 수 있다
        if (request.isAsyncStarted()) {
            sb.append("async");
        } else {
            sb.append(response.getStatus());
        }
        sb.append(" (").append(ms).append("ms)");
        return sb.toString();
    }
}
