package com.sia.assistant;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;

/**
 * 컨텍스트 기동 스모크 테스트 — 빈 배선·Flyway 마이그레이션·도구 카탈로그 동기화가 한 번에 검증된다.
 * 실 운영 경로(sia.db, %APPDATA%/SIA)를 건드리지 않도록 build/ 아래로 격리하고,
 * WebSocket 컨테이너(wsContainer)가 실제 서블릿 컨테이너를 요구하므로 MOCK 대신 임의 포트로 띄운다.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
class AssistantApplicationTests {

    @Autowired
    private JdbcTemplate jdbc;

    @DynamicPropertySource
    static void isolateRuntimePaths(DynamicPropertyRegistry registry) throws IOException {
        Path dir = Path.of("build", "test-data");
        Files.createDirectories(dir);
        // ★ 매번 빈 DB 로 시작한다. 이 파일은 build/ 아래에 남아 다음 실행까지 살아 있는데,
        //   V1 마이그레이션을 한 글자만 고쳐도 Flyway 체크섬이 어긋나 컨텍스트가 통째로 뜨지 않는다.
        //   마이그레이션 자체를 검증하는 테스트이므로 새로 만드는 게 맞다.
        for (String suffix : new String[]{"", "-wal", "-shm"}) {
            Files.deleteIfExists(dir.resolve("sia-test.db" + suffix));
        }
        registry.add("spring.datasource.url", () -> "jdbc:sqlite:" + dir.resolve("sia-test.db"));
        registry.add("sia.data-dir", () -> dir.toString());
    }

    @Test
    @DisplayName("애플리케이션 컨텍스트가 뜬다")
    void contextLoads() {
    }

    @Test
    @DisplayName("기동이 도구 목록과 기본 제공 제스처를 DB 에 넣는다 — 마이그레이션 시드 없이")
    void bootSeedsToolsAndBuiltinGestures() {
        // ToolCatalogSync(@Order 0) — ToolCatalog 31개가 tool 테이블에 올라간다
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM tool", Integer.class)).isEqualTo(31);
        // 카탈로그에만 있고 @McpTool 이 없는 도구는 available = 0 으로 조용히 내려앉아 LLM 이 못 부른다
        assertThat(jdbc.queryForList("SELECT name FROM tool WHERE available = 0", String.class)).isEmpty();
        // DefaultGestureBootstrap(@Order 5) — 기본 제공 제스처 9종. 행동은 사용자가 지정하므로 스텝은 0건이다
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM gesture", Integer.class)).isEqualTo(9);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM gesture_step", Integer.class)).isZero();
        // 전부 컨텍스트 없는 한손 HAND, 스와이프 2종만 동작(DYNAMIC)이다. FACE 시드는 없다
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM gesture WHERE custom = 0 AND kind = 'HAND'"
                + " AND context IS NULL AND hands = 1 AND enabled = 1", Integer.class)).isEqualTo(9);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM gesture WHERE motion = 'STATIC'",
                Integer.class)).isEqualTo(7);
        assertThat(jdbc.queryForList("SELECT name FROM gesture WHERE motion = 'DYNAMIC' ORDER BY name",
                String.class)).containsExactly("Swipe_Left", "Swipe_Right");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM gesture WHERE kind = 'FACE'",
                Integer.class)).isZero();
    }
}
