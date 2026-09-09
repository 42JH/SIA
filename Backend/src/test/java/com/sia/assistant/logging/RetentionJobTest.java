package com.sia.assistant.logging;

import static org.assertj.core.api.Assertions.assertThat;

import com.sia.assistant.common.Times;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/**
 * ★ 보존이 400일이라 이 잡은 <b>첫 400일 동안 아무것도 지우지 않는다</b> — 실사용으로는
 * 삭제 경로가 한 번도 실행되지 않은 채 굴러간다. 그래서 컷오프를 주입해 여기서 대신 검증한다.
 */
class RetentionJobTest {

    private JdbcTemplate jdbc;
    private RetentionJob job;

    @BeforeEach
    void setUp(@TempDir Path dir) {
        DriverManagerDataSource ds = new DriverManagerDataSource(
                "jdbc:sqlite:" + dir.resolve("retention-test.db"));
        Flyway.configure().dataSource(ds).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(ds);
        job = new RetentionJob(jdbc);
    }

    @Test
    @DisplayName("보존 기간은 400일이다 — 대시보드의 12개월 축을 원본으로 덮는다")
    void retentionCoversTheLongestAxis() {
        // 월 버킷 12개를 채우려면 11개월 전 1일까지 필요하다. 365 로는 달 길이에 따라 잘린다
        assertThat(RetentionJob.RETENTION_DAYS).isGreaterThan(366);
    }

    @Test
    @DisplayName("컷오프보다 오래된 기록만 지운다 — 경계의 최신 쪽은 남는다")
    void purgeDropsOnlyRowsOlderThanCutoff() {
        Instant old = Instant.now().minus(Duration.ofDays(500));
        Instant fresh = Instant.now().minus(Duration.ofDays(300));
        event(old);
        event(fresh);
        session(old, true);
        session(fresh, true);

        job.purgeBefore(Times.of(Instant.now().minus(Duration.ofDays(400))));

        assertThat(count("usage_event")).isEqualTo(1);
        assertThat(count("session")).isEqualTo(1);
    }

    @Test
    @DisplayName("진행 중인 세션은 아무리 오래돼도 지우지 않는다")
    void openSessionsSurvivePurge() {
        session(Instant.now().minus(Duration.ofDays(500)), false);

        job.purgeBefore(Times.of(Instant.now().minus(Duration.ofDays(400))));

        assertThat(count("session")).isEqualTo(1);
    }

    @Test
    @DisplayName("지울 게 없어도 조용히 끝난다 — 첫 400일의 정상 상태다")
    void purgeIsQuietWhenNothingIsOldEnough() {
        event(Instant.now());

        job.purgeBefore(Times.of(Instant.now().minus(Duration.ofDays(400))));

        assertThat(count("usage_event")).isEqualTo(1);
    }

    private void event(Instant at) {
        jdbc.update("INSERT INTO usage_event (event_uid, received_at, kind, payload)"
                + " VALUES (?, ?, 'voice', '{}')", UUID.randomUUID().toString(), Times.of(at));
    }

    private void session(Instant at, boolean ended) {
        jdbc.update("INSERT INTO session (started_at, ended_at, end_reason) VALUES (?, ?, ?)",
                Times.of(at), ended ? Times.of(at.plusSeconds(90)) : null, ended ? "EXPIRED" : null);
    }

    private int count(String table) {
        Integer n = jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Integer.class);
        return n == null ? 0 : n;
    }
}
