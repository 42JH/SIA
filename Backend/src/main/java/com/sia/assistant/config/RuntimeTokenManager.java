package com.sia.assistant.config;

import jakarta.annotation.PostConstruct;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

/**
 * MCP 공유 토큰 + runtime.json.
 * 토큰은 고정값 'sia-mcp-server' (SIA_AGENT_TOKEN 환경변수로 대체 가능) — 전부 로컬이라 고정이 기본이다.
 * AI 는 runtime.json 에서 {token, port, pid} 를 읽어 접속한다. DB 가 열리기 전에 필요한 값이라 DB 에 넣지 않는다.
 */
@Component
public class RuntimeTokenManager {

    public static final String DEFAULT_TOKEN = "sia-mcp-server";

    private static final Logger log = LoggerFactory.getLogger(RuntimeTokenManager.class);

    private final DataDirs dirs;
    private final ObjectMapper om;
    private final int port;
    private final String token;

    public RuntimeTokenManager(DataDirs dirs, ObjectMapper om, @Value("${server.port:8080}") int port) {
        this.dirs = dirs;
        this.om = om;
        this.port = port;
        String env = System.getenv("SIA_AGENT_TOKEN");
        this.token = (env == null || env.isBlank()) ? DEFAULT_TOKEN : env.trim();
    }

    public String token() {
        return token;
    }

    @PostConstruct
    void writeRuntimeFile() {
        Path file = dirs.root().resolve("runtime.json");
        try {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("token", token);
            body.put("port", port);
            body.put("pid", ProcessHandle.current().pid());
            Files.createDirectories(dirs.root());
            Files.writeString(file, om.writeValueAsString(body));
            log.info("runtime.json 기록: {}", file);
        } catch (Exception e) {
            // 파일을 못 써도 서버는 뜬다 — 대신 AI 가 토큰을 못 얻어 401 을 받는다. 이 로그를 먼저 볼 것.
            log.error("runtime.json 기록 실패: {}", file, e);
        }
    }
}
