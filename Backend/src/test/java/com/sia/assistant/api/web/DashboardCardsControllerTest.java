package com.sia.assistant.api.web;

import static org.assertj.core.api.Assertions.assertThat;

import com.sia.assistant.common.Times;
import java.nio.file.Path;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneId;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/**
 * 진짜 SQLite + 진짜 마이그레이션으로 돌린다 — 이 카드들의 로직은 대부분 SQL 이라
 * JdbcTemplate 을 모킹하면 아무것도 검증되지 않는다. usage_event 의 accuracy·complexity 컬럼도 여기서 함께 검증된다.
 */
class DashboardCardsControllerTest {

    private JdbcTemplate jdbc;
    private DashboardCardsController controller;

    @BeforeEach
    void setUp(@TempDir Path dir) {
        DriverManagerDataSource ds = new DriverManagerDataSource(
                "jdbc:sqlite:" + dir.resolve("dash-test.db"));
        Flyway.configure().dataSource(ds).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(ds);
        controller = new DashboardCardsController(jdbc);
    }

    // ------------------------------------------------------------------ 인식 정확도
    @Test
    @DisplayName("표본이 없는 계열은 0 이 아니라 null 이다 — 0% 는 거짓말이다")
    void emptySeriesIsNullNotZero() {
        event("voice", 0.9, null, null, minutesAgo(5));

        Map<String, Object> body = controller.accuracy("day");
        Map<String, Object> summary = summaryOf(body);

        assertThat(summary.get("voice")).isEqualTo(0.9);
        assertThat(summary.get("gaze")).isNull();
        assertThat(summary.get("motion")).isNull();
        // 버킷도 마찬가지 — 빈 칸은 채우되 평균은 null 이다
        assertThat(bucketsOf(body)).hasSize(8);
        assertThat(bucketsOf(body)).anySatisfy(b -> {
            assertThat(b.get("voice")).isNull();
            assertThat(b.get("sampleCount")).isEqualTo(0L);
        });
    }

    @Test
    @DisplayName("summary 는 버킷 평균의 평균이 아니라 기간 전체 재집계다")
    void summaryReaggregatesOverWholePeriod() {
        event("voice", 1.0, null, null, minutesAgo(5));
        event("voice", 0.9, null, null, minutesAgo(6));
        event("gesture", 0.8, null, null, minutesAgo(7));

        Map<String, Object> summary = summaryOf(controller.accuracy("day"));

        assertThat(summary.get("voice")).isEqualTo(0.95);
        assertThat(summary.get("motion")).isEqualTo(0.8);
        assertThat(summary.get("sampleCount")).isEqualTo(3L);
    }

    @Test
    @DisplayName("화자 게이트가 버린 발화(voice-rejected)는 정확도에도 사용량에도 섞이지 않는다")
    void voiceRejectedIsExcludedFromUserFacingCards() {
        event("voice", 0.9, null, null, minutesAgo(5));
        event("voice-rejected", 0.2, null, null, minutesAgo(5));

        assertThat(summaryOf(controller.accuracy("day")).get("voice")).isEqualTo(0.9);
        assertThat(summaryOf(controller.usage("day")).get("total")).isEqualTo(1L);
    }

    // ------------------------------------------------------------------ 응답 시간
    @Test
    @DisplayName("전체 평균은 표본 가중 평균이다 — (간단 + 복잡) / 2 가 아니다")
    void overallLatencyIsSampleWeighted() {
        event("command", null, 800, "SIMPLE", minutesAgo(5));
        event("command", null, 800, "SIMPLE", minutesAgo(6));
        event("command", null, 2300, "COMPLEX", minutesAgo(7));

        Map<String, Object> summary = summaryOf(controller.latency("day"));

        assertThat(summary.get("simpleMs")).isEqualTo(800L);
        assertThat(summary.get("complexMs")).isEqualTo(2300L);
        // (800*2 + 2300) / 3 = 1300. 단순 평균이면 1550 이 나온다
        assertThat(summary.get("overallMs")).isEqualTo(1300L);
        assertThat(summary.get("simpleCount")).isEqualTo(2L);
    }

    @Test
    @DisplayName("complexity 가 없는 command 는 SIMPLE 로 넘겨짚지 않고 통째로 제외한다")
    void commandWithoutComplexityIsExcluded() {
        event("command", null, 5000, null, minutesAgo(5));

        Map<String, Object> summary = summaryOf(controller.latency("day"));

        assertThat(summary.get("simpleMs")).isNull();
        assertThat(summary.get("overallMs")).isNull();
        assertThat(summary.get("simpleCount")).isEqualTo(0L);
    }

    // ------------------------------------------------------------------ 사용량
    @Test
    @DisplayName("사용량은 제스처 + 보이스 합산이고, 평균 분모는 버킷 수가 아니다")
    void usageCountsAndAverage() {
        for (int i = 0; i < 12; i++) {
            event("gesture", null, null, null, minutesAgo(5 + i));
        }
        Map<String, Object> summary = summaryOf(controller.usage("day"));

        assertThat(summary.get("total")).isEqualTo(12L);
        assertThat(summary.get("averageUnit")).isEqualTo("HOUR");
        assertThat(summary.get("average")).isEqualTo(0.5);   // 12 / 24, 버킷 8 이 아니다
    }

    @Test
    @DisplayName("최다 버킷이 동률이면 먼저 오는 버킷을 고른다")
    void peakPrefersEarlierBucketOnTie() {
        Instant earlier = daysAgo(3);
        Instant later = daysAgo(2);
        event("gesture", null, null, null, earlier);
        event("voice", null, null, null, later);

        Map<String, Object> peak = castMap(summaryOf(controller.usage("week")).get("peak"));

        // 둘 다 1회 — 동률이다. 버킷 인덱스를 박아 두면 실행 시각에 흔들리므로 같은 시각에서 유도한다
        assertThat(peak.get("count")).isEqualTo(1L);
        assertThat(peak.get("key"))
                .isEqualTo(earlier.atZone(ZoneId.systemDefault()).toLocalDate().toString());
    }

    @Test
    @DisplayName("전 구간이 0 이면 peak 은 null 이다")
    void peakIsNullWhenNothingHappened() {
        assertThat(summaryOf(controller.usage("day")).get("peak")).isNull();
    }

    // ------------------------------------------------------------------ 프로그램
    @Test
    @DisplayName("실행된 app.launch 만 센다 — 차단·실패는 사용이 아니다")
    void appsCountOnlyExecutedLaunches() {
        long chrome = app("chrome", "크롬");
        long slack = app("slack", "슬랙");
        launch(chrome, "EXECUTED", minutesAgo(5));
        launch(chrome, "EXECUTED", minutesAgo(6));
        launch(chrome, "BLOCKED", minutesAgo(7));
        launch(slack, "EXECUTED", minutesAgo(8));

        Map<String, Object> body = controller.apps("day", 10);
        List<Map<String, Object>> items = castList(body.get("items"));
        Map<String, Object> summary = summaryOf(body);

        assertThat(items).hasSize(2);
        assertThat(items.get(0)).containsEntry("appKey", "chrome")
                .containsEntry("displayName", "크롬")
                .containsEntry("count", 2L);
        assertThat(summary.get("totalLaunches")).isEqualTo(3L);
        assertThat(summary.get("topAppKey")).isEqualTo("chrome");
        assertThat(items.get(0).get("share")).isEqualTo(0.667);
    }

    @Test
    @DisplayName("limit 에 잘려도 totalLaunches 는 잘리기 전 전체 합이다")
    void totalLaunchesIgnoresLimit() {
        launch(app("a", "A"), "EXECUTED", minutesAgo(5));
        launch(app("b", "B"), "EXECUTED", minutesAgo(6));
        launch(app("c", "C"), "EXECUTED", minutesAgo(7));

        Map<String, Object> body = controller.apps("day", 1);

        assertThat(castList(body.get("items"))).hasSize(1);
        assertThat(summaryOf(body).get("totalLaunches")).isEqualTo(3L);
    }

    @Test
    @DisplayName("등록 해제된 앱의 실행 기록도 카드에 남는다 — appKey 는 기록의 appRef 에서 복원한다")
    void deletedAppStaysInCardWithAppKey() {
        long chrome = app("chrome", "크롬");
        launchWithArgs(chrome, "{\"appRef\":\"app:chrome\"}", minutesAgo(5));
        launchWithArgs(chrome, "{\"appRef\":\"app:chrome\"}", minutesAgo(6));
        launchWithArgs(app("slack", "슬랙"), "{\"appRef\":\"app:slack\"}", minutesAgo(7));
        jdbc.update("DELETE FROM app_target WHERE id = ?", chrome);   // DELETE /api/apps/chrome 과 같다

        Map<String, Object> body = controller.apps("day", 10);
        List<Map<String, Object>> items = castList(body.get("items"));
        Map<String, Object> summary = summaryOf(body);

        assertThat(items).hasSize(2);
        assertThat(items.get(0)).containsEntry("appKey", "chrome")
                .containsEntry("displayName", "chrome")
                .containsEntry("count", 2L);
        assertThat(items.get(1)).containsEntry("appKey", "slack").containsEntry("displayName", "슬랙");
        assertThat(summary.get("totalLaunches")).isEqualTo(3L);
        assertThat(summary.get("topAppKey")).isEqualTo("chrome");
    }

    // ------------------------------------------------------------------ 첫 화면
    @Test
    @DisplayName("overview 는 카드 4개를 한 번에 준다")
    void overviewBundlesFourCards() {
        event("voice", 0.96, null, null, minutesAgo(5));
        event("command", null, 800, "SIMPLE", minutesAgo(5));
        launch(app("chrome", "크롬"), "EXECUTED", minutesAgo(5));

        Map<String, Object> body = controller.overview();

        assertThat(body).containsKeys("generatedAt", "accuracy", "latency", "usage", "topApps");
        assertThat(castMap(body.get("accuracy"))).containsEntry("period", "week")
                .containsEntry("voice", 0.96);
        assertThat(castMap(body.get("latency"))).containsEntry("simpleMs", 800L);
        assertThat(castList(castMap(body.get("usage")).get("buckets"))).hasSize(7);
        assertThat(castList(body.get("topApps"))).hasSize(1);
    }

    // ------------------------------------------------------------------ 픽스처
    private void event(String kind, Double accuracy, Integer latencyMs, String complexity, Instant at) {
        jdbc.update("INSERT INTO usage_event (event_uid, received_at, kind, latency_ms, accuracy,"
                        + " complexity, payload) VALUES (?, ?, ?, ?, ?, ?, '{}')",
                UUID.randomUUID().toString(), Times.of(at), kind, latencyMs, accuracy, complexity);
    }

    private long app(String key, String name) {
        jdbc.update("INSERT INTO app_target (app_key, display_name, exec_path) VALUES (?, ?, 'x.exe')",
                key, name);
        Long id = jdbc.queryForObject("SELECT id FROM app_target WHERE app_key = ?", Long.class, key);
        return id == null ? 0L : id;
    }

    private void launch(long appTargetId, String outcome, Instant at) {
        jdbc.update("INSERT INTO tool_call (session_id, app_target_id, tool_name, ts, args_json,"
                        + " caller, outcome) VALUES (NULL, ?, 'app.launch', ?, '{}', 'LLM', ?)",
                appTargetId, Times.of(at), outcome);
    }

    private void launchWithArgs(long appTargetId, String argsJson, Instant at) {
        jdbc.update("INSERT INTO tool_call (session_id, app_target_id, tool_name, ts, args_json,"
                        + " caller, outcome) VALUES (NULL, ?, 'app.launch', ?, ?, 'LLM', 'EXECUTED')",
                appTargetId, Times.of(at), argsJson);
    }

    private static Instant minutesAgo(int m) {
        return Instant.now().minus(Duration.ofMinutes(m));
    }

    /** 정오로 맞춰 로컬 자정 경계에 걸치지 않게 한다 — 버킷이 흔들리면 테스트가 아니라 시계를 재는 꼴이다. */
    private static Instant daysAgo(int d) {
        return Instant.now().minus(Duration.ofDays(d)).minus(Duration.ofHours(2));
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> summaryOf(Map<String, Object> body) {
        return (Map<String, Object>) body.get("summary");
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> bucketsOf(Map<String, Object> body) {
        return (List<Map<String, Object>>) body.get("buckets");
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> castMap(Object o) {
        return (Map<String, Object>) o;
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> castList(Object o) {
        return (List<Map<String, Object>>) o;
    }
}
