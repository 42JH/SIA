package com.sia.assistant.config;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.WebSocket;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;
import java.util.stream.Stream;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.context.ApplicationContext;
import org.springframework.http.server.PathContainer;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.web.servlet.HandlerMapping;
import org.springframework.web.servlet.handler.AbstractUrlHandlerMapping;
import org.springframework.web.servlet.mvc.method.annotation.RequestMappingHandlerMapping;
import org.springframework.web.util.pattern.PathPattern;
import org.springframework.web.util.pattern.PathPatternParser;

/**
 * 보안 경계 회귀망. 두 방향을 같은 무게로 지킨다:
 *  ① 보호 경로는 토큰 없이 어떤 표기로도 열리지 않는다 (퍼센트 인코딩 우회 제보)
 *  ② allow-list 는 살아 있다 — deny-by-default 로 뒤집었으니 FE·AI·스웨거가 죽지 않는지가 같이 중요하다
 *
 * <p>MockMvc 가 아니라 실제 Tomcat 이어야 한다: 디코딩 시점이 쟁점이라 서블릿 컨테이너가 진짜여야 한다.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class SecurityBoundaryTest {

    private static final String INIT_BODY = """
            {"jsonrpc":"2.0","id":1,"method":"initialize","params":{\
            "protocolVersion":"2024-11-05","capabilities":{},\
            "clientInfo":{"name":"probe","version":"1.0"}}}""";

    @LocalServerPort
    private int port;

    @Autowired
    private ApplicationContext ctx;

    @DynamicPropertySource
    static void isolateRuntimePaths(DynamicPropertyRegistry registry) throws IOException {
        Path dir = Path.of("build", "security-boundary");
        Files.createDirectories(dir);
        for (String suffix : new String[]{"", "-wal", "-shm"}) {
            Files.deleteIfExists(dir.resolve("probe.db" + suffix));
        }
        registry.add("spring.datasource.url", () -> "jdbc:sqlite:" + dir.resolve("probe.db"));
        registry.add("sia.data-dir", () -> dir.toString());
    }

    /** /mcp 를 가리키는 표기 변형들. 라우팅이 디코딩 후 값으로 가므로 전부 같은 곳에 닿는다. */
    static Stream<String> mcp표기변형() {
        return Stream.of("/mcp", "/%6dcp", "/%6D%63%70", "/mc%70", "/m%63p");
    }

    @ParameterizedTest(name = "{0}")
    @MethodSource("mcp표기변형")
    @DisplayName("① 토큰 없이는 어떤 표기로도 MCP 세션이 열리지 않는다")
    void 무토큰_MCP_차단(String path) throws Exception {
        HttpResponse<String> r = post(path, null);

        // 표기에 따라 401(인가) / 400(StrictHttpFirewall) / 404 로 갈릴 수 있다.
        // 지켜야 할 선은 하나다 — 세션이 열리지 않는다.
        assertThat(r.headers().firstValue("mcp-session-id")).as("%s 가 세션을 발급했다", path).isEmpty();
        assertThat(r.statusCode()).as("%s", path).isNotEqualTo(200);
    }

    @Test
    @DisplayName("① 토큰이 맞으면 MCP 는 정상 동작한다")
    void 정상토큰은_통과() throws Exception {
        HttpResponse<String> r = post("/mcp", RuntimeTokenManager.DEFAULT_TOKEN);

        assertThat(r.statusCode()).isEqualTo(200);
        assertThat(r.headers().firstValue("mcp-session-id")).isPresent();
    }

    @ParameterizedTest(name = "{0}")
    @ValueSource(strings = {
            "/api/status",                                  // FE·AI 의 REST
            "/v3/api-docs",                                 // 스웨거 문서(JSON)
            "/v3/api-docs.yaml",                            // ★ /v3/api-docs/** 로는 안 잡히던 변형
            "/v3/api-docs/swagger-config",
            "/swagger-ui/index.html",
            "/webjars/swagger-ui/5.32.11/swagger-ui.css",   // ★ 이게 막히면 스웨거 UI 가 깨진 채로 뜬다
    })
    @DisplayName("② allow-list 경로는 토큰 없이 그대로 열려 있다")
    void allowlist는_살아있다(String path) throws Exception {
        assertThat(get(path).statusCode()).as("%s", path).isEqualTo(200);
    }

    @Test
    @DisplayName("② WebSocket 핸드셰이크(/ws/fe)가 토큰 없이 붙는다")
    void 웹소켓_핸드셰이크() throws Exception {
        WebSocket ws = HttpClient.newHttpClient().newWebSocketBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .buildAsync(URI.create("ws://127.0.0.1:" + port + "/ws/fe"), new WebSocket.Listener() {
                })
                .join();

        assertThat(ws).isNotNull();
        ws.abort();
    }

    @Test
    @DisplayName("② 없는 /api 경로는 401 이 아니라 404 다 — 에러 디스패치가 잠기지 않았다")
    void 에러_디스패치() throws Exception {
        assertThat(get("/api/no-such-endpoint").statusCode()).isEqualTo(404);
    }

    @Test
    @DisplayName("③ 경로 판정에 getRequestURI() 를 쓰지 않는다 — raw 라서 /%6dcp 가 /mcp 와 달라 보인다")
    void raw경로로_판정하지_않는다() throws IOException {
        // 찍는 건 허용(로그엔 원문이 맞다). 금지 대상은 '판정' — 비교 메서드가 바로 붙는 경우다.
        List<String> violations;
        try (Stream<Path> files = Files.walk(Path.of("src", "main", "java"))) {
            violations = files.filter(f -> f.toString().endsWith(".java"))
                    .filter(f -> {
                        try {
                            return Files.readString(f)
                                    .matches("(?s).*getRequestURI\\(\\)\\s*\\.\\s*"
                                            + "(startsWith|equals|equalsIgnoreCase|contains|endsWith|matches)\\b.*");
                        } catch (IOException e) {
                            throw new RuntimeException(e);
                        }
                    })
                    .map(Path::toString).toList();
        }

        assertThat(violations)
                .as("경로 판정은 RequestPaths.of() 나 SecurityConfig 의 requestMatchers 로 한다")
                .isEmpty();
    }

    /**
     * 정적 리소스 캐치올. 실제 엔드포인트가 아니고 파일이 없으면 어차피 404 라 잠가 둔다
     * (deny-by-default 라 404 대신 401 이 나가는데, 없는 파일이므로 문제되지 않는다).
     */
    private static final Set<String> 의도적_잠금 = Set.of("/**");

    @Test
    @DisplayName("④ 등록된 모든 경로는 allow-list 에 있거나 의도적으로 잠겨 있다 — 새 엔드포인트 누락 감지")
    void 모든_경로가_분류돼_있다() {
        PathPatternParser parser = PathPatternParser.defaultInstance;
        List<PathPattern> open = Arrays.stream(SecurityConfig.OPEN_PATHS).map(parser::parse).toList();

        List<String> 미분류 = new ArrayList<>();
        for (HandlerMapping hm : ctx.getBeansOfType(HandlerMapping.class).values()) {
            for (String declared : 경로꺼내기(hm)) {
                // {id} · {file:[a-z]+\.png} 같은 템플릿은 구체값으로 바꿔 놓고 매칭한다
                String concrete = declared.replaceAll("\\{[^{}]*\\}", "x");
                boolean allowed = open.stream()
                        .anyMatch(p -> p.matches(PathContainer.parsePath(concrete)));
                if (!allowed && !의도적_잠금.contains(declared)) {
                    미분류.add(declared);
                }
            }
        }

        assertThat(미분류)
                .as("새 REST·WebSocket 경로를 추가했다면 SecurityConfig.OPEN_PATHS 에 넣거나,"
                        + " 인증이 필요한 경로라면 이 테스트의 '의도적_잠금' 에 근거와 함께 적어라")
                .isEmpty();
    }

    /** RouterFunctionMapping(/mcp)은 열거할 수 없다 — 그건 위 ①이 표기 변형까지 직접 때려서 지킨다. */
    private static Set<String> 경로꺼내기(HandlerMapping hm) {
        Set<String> paths = new TreeSet<>();
        if (hm instanceof RequestMappingHandlerMapping rm) {
            rm.getHandlerMethods().keySet().stream()
                    .filter(info -> info.getPathPatternsCondition() != null)
                    .forEach(info -> paths.addAll(info.getPathPatternsCondition().getPatternValues()));
        } else if (hm instanceof AbstractUrlHandlerMapping um) {
            paths.addAll(um.getHandlerMap().keySet());
        }
        return paths;
    }

    private HttpResponse<String> post(String rawPath, String token) throws Exception {
        HttpRequest.Builder b = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + rawPath))
                .timeout(Duration.ofSeconds(15))
                .header("Content-Type", "application/json")
                .header("Accept", "application/json, text/event-stream")
                .POST(HttpRequest.BodyPublishers.ofString(INIT_BODY));
        if (token != null) {
            b.header("Authorization", "Bearer " + token);
        }
        return HttpClient.newHttpClient().send(b.build(), HttpResponse.BodyHandlers.ofString());
    }

    private HttpResponse<String> get(String path) throws Exception {
        HttpRequest req = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + path))
                .timeout(Duration.ofSeconds(15)).GET().build();
        return HttpClient.newHttpClient().send(req, HttpResponse.BodyHandlers.ofString());
    }
}
