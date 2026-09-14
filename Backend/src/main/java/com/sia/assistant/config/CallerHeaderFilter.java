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
 * 요청 헤더 X-Caller(LLM | GESTURE) → CallerContext(ThreadLocal).
 *
 * <p>경로로 범위를 좁히지 않는다 — 이 ThreadLocal 은 MCP 도구 실행부만 읽고 아래 finally 가 지우므로,
 * 다른 경로에서 설정돼도 무해하다. 경로 판정을 두면 /%6dcp 같은 인코딩 경로에서 X-Caller 가
 * 조용히 무시돼 GESTURE 호출이 LLM 으로 기록된다.
 * AI 의 제스처 직행 경로와 LLM 경로가 같은 도구를 지나므로 이 헤더가 caller 구분의 유일한 근거다.
 */
@Component
public class CallerHeaderFilter extends OncePerRequestFilter {

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
