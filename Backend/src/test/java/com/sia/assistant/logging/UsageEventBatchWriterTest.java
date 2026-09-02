package com.sia.assistant.logging;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.nio.file.Path;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/**
 * accuracy · complexity 는 payload 가 아니라 컬럼으로 받는다 — 대시보드가 GROUP BY·AVG 하는 값이라서다.
 * 값이 이상하면 <b>그 필드만</b> null 로 낮추고 이벤트는 살린다 (통계는 관대하게 받는다).
 */
class UsageEventBatchWriterTest {

    private JdbcTemplate jdbc;
    private UsageEventBatchWriter writer;

    @BeforeEach
    void setUp(@TempDir Path dir) {
        DriverManagerDataSource ds = new DriverManagerDataSource(
                "jdbc:sqlite:" + dir.resolve("events-test.db"));
        Flyway.configure().dataSource(ds).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(ds);
        writer = new UsageEventBatchWriter(jdbc, new ObjectMapper());
    }

    @Test
    @DisplayName("accuracy·complexity 를 컬럼으로 저장한다")
    void storesTheTwoDashboardColumns() {
        UsageEventBatchWriter.Result result = writer.write(List.of(
                event("e1", "voice", Map.of("accuracy", 0.93)),
                event("e2", "command", Map.of("latencyMs", 2410, "complexity", "complex"))));

        assertThat(result.accepted()).isEqualTo(2);
        assertThat(one("SELECT accuracy FROM usage_event WHERE event_uid = 'e1'")).isEqualTo(0.93);
        // 소문자로 와도 정규화한다
        assertThat(one("SELECT complexity FROM usage_event WHERE event_uid = 'e2'")).isEqualTo("COMPLEX");
    }

    @Test
    @DisplayName("profileId 를 컬럼으로 저장한다 — 프로필별 인식 정확도(롤백 판단)의 축")
    void storesProfileIdColumn() {
        UsageEventBatchWriter.Result result = writer.write(List.of(
                event("p1", "voice", Map.of("accuracy", 0.9, "profileId", 3)),
                event("p2", "gaze", Map.of("accuracy", 0.8)),
                event("p3", "voice", Map.of("profileId", "숫자아님"))));

        assertThat(result.accepted()).isEqualTo(3);
        assertThat(one("SELECT profile_id FROM usage_event WHERE event_uid = 'p1'")).isEqualTo(3);
        assertThat(one("SELECT profile_id FROM usage_event WHERE event_uid = 'p2'")).isNull();
        // 이상한 값은 그 필드만 null 로 낮춘다 — 이벤트는 살린다
        assertThat(one("SELECT profile_id FROM usage_event WHERE event_uid = 'p3'")).isNull();
    }

    @Test
    @DisplayName("범위를 벗어난 accuracy 는 그 필드만 null 로 낮춘다 — 이벤트는 버리지 않는다")
    void outOfRangeAccuracyIsDemotedNotRejected() {
        UsageEventBatchWriter.Result result = writer.write(List.of(
                event("e1", "voice", Map.of("accuracy", 1.4)),
                event("e2", "voice", Map.of("accuracy", -0.1)),
                event("e3", "voice", Map.of("accuracy", "몰라요"))));

        assertThat(result.accepted()).isEqualTo(3);
        assertThat(result.rejected()).isZero();
        assertThat(jdbc.queryForObject(
                "SELECT COUNT(*) FROM usage_event WHERE accuracy IS NULL", Integer.class))
                .isEqualTo(3);
    }

    @Test
    @DisplayName("모르는 complexity 는 SIMPLE 로 넘겨짚지 않고 null 이다")
    void unknownComplexityIsNullNotGuessed() {
        writer.write(List.of(event("e1", "command", Map.of("latencyMs", 900, "complexity", "EASY"))));

        assertThat(one("SELECT complexity FROM usage_event WHERE event_uid = 'e1'")).isNull();
        // latencyMs 는 그대로 남는다 — 이벤트를 버린 게 아니다
        assertThat(one("SELECT latency_ms FROM usage_event WHERE event_uid = 'e1'")).isEqualTo(900);
    }

    @Test
    @DisplayName("같은 배치를 다시 보내면 duplicates 로 센다 (event_uid UNIQUE)")
    void resendIsIdempotent() {
        List<Map<String, Object>> batch = List.of(event("e1", "voice", Map.of("accuracy", 0.9)));

        assertThat(writer.write(batch).accepted()).isEqualTo(1);
        UsageEventBatchWriter.Result again = writer.write(batch);
        assertThat(again.accepted()).isZero();
        assertThat(again.duplicates()).isEqualTo(1);
    }

    private static Map<String, Object> event(String uid, String kind, Map<String, Object> extra) {
        Map<String, Object> e = new HashMap<>(extra);
        e.put("eventUid", uid);
        e.put("kind", kind);
        return e;
    }

    private Object one(String sql) {
        return jdbc.queryForObject(sql, Object.class);
    }
}
