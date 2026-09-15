package com.sia.assistant.config;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.List;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * 공유 토큰(Authorization: Bearer 또는 X-MC-Token)이 맞으면 ROLE_MCP 인증을 심는다.
 *
 * <p>★ 이 필터는 <b>경로를 보지 않고 401 도 내지 않는다.</b> 누구를 막을지는 SecurityConfig 의
 * authorizeHttpRequests 가 정한다. 경로 판정을 직접 하면 getRequestURI() 가 디코딩 전 값이라
 * /%6dcp 같은 인코딩 경로가 /mcp 와 달라 보이는데, 라우팅은 디코딩 후 값으로 가서 검사가 빗나간다.
 * 매칭은 라우팅과 같은 기계(PathPattern)에 맡기는 것이 유일하게 안전하다.
 *
 * <p>★ 스프링 빈이 아니다. Boot 는 컨텍스트의 모든 Filter 빈을 서블릿 컨테이너에 자동 등록하는데,
 * 그러면 시큐리티 체인 밖에서 한 번 더 돌아 인가 판정을 우회한다. SecurityConfig 가 직접 생성한다.
 *
 * <p>역할은 같은 PC 의 다른 프로세스가 실수로 MCP 를 부르는 것을 막는 문턱이고,
 * 원격 방어는 루프백 바인딩의 몫이다.
 */
public class SharedTokenFilter extends OncePerRequestFilter {

    private final RuntimeTokenManager tokens;

    public SharedTokenFilter(RuntimeTokenManager tokens) {
        this.tokens = tokens;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response,
                                    FilterChain chain) throws ServletException, IOException {
        String presented = extract(request);
        if (presented != null && constantTimeEquals(presented, tokens.token())) {
            SecurityContextHolder.getContext().setAuthentication(
                    UsernamePasswordAuthenticationToken.authenticated(
                            "mcp", null, List.of(new SimpleGrantedAuthority("ROLE_MCP"))));
        }
        chain.doFilter(request, response);
    }

    /**
     * ★ 비동기 디스패치에서도 돈다 (OncePerRequestFilter 기본값은 건너뛰기다).
     *
     * <p>MCP 도구 호출은 응답을 SSE 로 이어 가므로 요청 한 건이 최초 디스패치와 비동기 디스패치로 나뉜다.
     * 인가(AuthorizationFilter)는 디스패치 종류를 가리지 않고 매번 판정하는데, 세션을 안 쓰므로
     * (STATELESS) 최초 디스패치에 심은 인증은 그때 남아 있지 않다. 건너뛰면 이미 200 + text/event-stream
     * 으로 커밋된 응답이 비동기 디스패치에서 deny-by-default 에 걸려 그대로 끊긴다 — 클라이언트에는
     * 도구 결과 대신 EOF 가 가고, 도구를 부를 때마다 MCP 세션을 새로 여는 것으로 보인다.
     * 토큰은 헤더로 매 디스패치마다 다시 제시되므로 여기서 다시 심는 것이 맞다.
     */
    @Override
    protected boolean shouldNotFilterAsyncDispatch() {
        return false;
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
