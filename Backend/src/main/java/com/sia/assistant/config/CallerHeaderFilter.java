package com.sia.assistant.config;

import com.sia.assistant.mcp.Caller;
import com.sia.assistant.mcp.CallerContext;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * MCP 요청 헤더 X-Caller(LLM | GESTURE) → CallerContext(ThreadLocal).
 * AI 의 제스처 직행 경로와 LLM 경로가 같은 도구를 지나므로 이 헤더가 caller 구분의 유일한 근거다.
 */
@Component
public class CallerHeaderFilter extends OncePerRequestFilter {

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !request.getRequestURI().startsWith("/mcp");
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String header = request.getHeader("X-Caller");
        Caller caller = Caller.LLM;
        if (header != null && header.trim().equalsIgnoreCase("GESTURE")) {
            caller = Caller.GESTURE;
        }
        CallerContext.set(caller);
        try {
            chain.doFilter(request, response);
        } finally {
            CallerContext.clear();
        }
    }
}
