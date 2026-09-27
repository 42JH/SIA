package com.sia.assistant.config;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.List;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.AuthenticationException;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

/**
 * 보안 경계는 3겹이다:
 *  ① 네트워크 — server.address 127.0.0.1 바인딩 (application.yml)
 *  ② 인가 — 아래 authorizeHttpRequests. 로컬 FE·AI 가 쓰는 경로만 열고 <b>나머지는 전부 잠근다</b>
 *  ③ 능력 상한 — ToolCatalog (도구 목록이 곧 LLM 이 할 수 있는 일의 상한)
 *
 * <p>★ ② 는 열 것만 적는 allow-list 다. 보호할 경로(/mcp)를 적지 않는 게 핵심이다 —
 * 적어 두면 그 문자열에 안 걸리는 변형(/%6dcp 처럼 퍼센트 인코딩한 것)이 열리는 쪽으로 빠져나간다.
 * 반대로 해 두면 같은 변형이 allow-list 에 안 걸려 <b>잠기는 쪽</b>으로 실패하고,
 * 앞으로 추가되는 엔드포인트도 기본이 잠김이다.
 * 매칭은 requestMatchers(PathPattern)가 하므로 라우팅과 같은 기준(디코딩된 경로)을 본다.
 */
@Configuration
@EnableWebSecurity
public class SecurityConfig {

    /**
     * 토큰 없이 열어 두는 경로. <b>여기에 없는 경로는 전부 인증이 필요하다.</b>
     *
     * <p>새 REST 엔드포인트나 WebSocket 을 추가했는데 로컬 FE·AI 가 토큰 없이 써야 한다면
     * 여기에 넣어야 한다. 안 넣으면 401 이다 — 조용히 열리는 것보다 시끄럽게 닫히는 게 낫다.
     * 빠뜨렸는지는 SecurityBoundaryTest 의 전수 검사가 잡는다.
     */
    static final String[] OPEN_PATHS = {
            "/api/**",                                  // FE·AI 의 REST
            "/ws/**",                                   // /ws/agent · /ws/fe · /ws/ext
            "/swagger-ui/**", "/swagger-ui.html",       // 스웨거 UI 페이지
            "/v3/api-docs*", "/v3/api-docs/**",         // ★ .yaml 변형까지 — /v3/api-docs/** 는 그걸 못 잡는다
            "/webjars/**",                              // ★ 스웨거 UI 가 CSS·JS 를 여기서 받는다
            "/error", "/favicon.ico",
    };

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http, RuntimeTokenManager tokens) throws Exception {
        http.csrf(csrf -> csrf.disable())
                .cors(cors -> {
                })
                // 토큰은 요청마다 제시된다 — 한 번 통과한 인증이 세션에 눌러앉지 않게 한다
                .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                .addFilterBefore(new SharedTokenFilter(tokens), UsernamePasswordAuthenticationFilter.class)
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers(OPEN_PATHS).permitAll()
                        .anyRequest().authenticated())
                .exceptionHandling(e -> e.authenticationEntryPoint(SecurityConfig::unauthorized));
        return http.build();
    }

    /** 인증 없이 잠긴 경로를 두드리면 기존과 같은 JSON 401 을 준다 (AI·도구가 파싱하는 형식이다). */
    private static void unauthorized(HttpServletRequest request, HttpServletResponse response,
                                     AuthenticationException e) throws IOException {
        response.setStatus(401);
        response.setContentType("application/json;charset=UTF-8");
        response.getWriter().write("{\"code\":\"UNAUTHORIZED\",\"message\":\"MCP 토큰이 필요합니다\"}");
    }

    @Bean
    public CorsConfigurationSource corsConfigurationSource() {
        CorsConfiguration config = new CorsConfiguration();
        config.setAllowedOriginPatterns(List.of("http://localhost:*", "http://127.0.0.1:*", "http://tauri.localhost"));
        config.setAllowedMethods(List.of("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"));
        config.setAllowedHeaders(List.of("*"));
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/api/**", config);
        return source;
    }
}
