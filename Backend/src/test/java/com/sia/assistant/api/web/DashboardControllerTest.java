package com.sia.assistant.api.web;

import static org.assertj.core.api.Assertions.assertThat;

import com.sia.assistant.common.Times;
import java.nio.file.Path;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.ZonedDateTime;
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
 * /timeseries 의 날짜 축은 <b>로컬</b>이다 — §1.15~§1.19 카드와 같은 하루를 써야 한다.
 * 예전에는 UTC 로 잘라서 KST 기준 오전 9시에 날짜가 바뀌었다.
 * 진짜 SQLite + 진짜 마이그레이션으로 돌린다 (로직 대부분이 SQL 이라 모킹하면 검증되는 게 없다).
 */
class DashboardControllerTest {

    private JdbcTemplate jdbc;
    private DashboardController controller;

    @BeforeEach
    void setUp(@TempDir Path dir) {
        DriverManagerDataSource ds = new DriverManagerDataSource(
                "jdbc:sqlite:" + dir.resolve("dash-ops-test.db"));
        Flyway.configure().dataSource(ds).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(ds);
        controller = new DashboardController(jdbc);
    }

    @Test
    @DisplayName("로컬 자정 직후의 호출은 UTC 로는 어제지만 오늘 칸에 들어간다")
    void countsLandOnTheLocalDay() {
        ZoneId zone = ZoneId.systemDefault();
        LocalDate today = LocalDate.now(zone);
        // 로컬 오늘 00:30 — KST 라면 UTC 로는 어제 15:30 이다
        toolCall(today.atStartOfDay(zone).plusMinutes(30));

        List<Map<String, Object>> items = itemsOf(controller.timeseries(7));

        assertThat(items).hasSize(7);
        assertThat(items.get(6).get("date")).isEqualTo(today.toString());
        assertThat(items.get(6).get("toolCalls")).isEqualTo(1L);
        assertThat(items.get(5).get("toolCalls")).isEqualTo(0L);
    }

    @Test
    @DisplayName("로컬 자정 직전의 호출은 어제 칸에 남는다 — 오늘로 새지 않는다")
    void previousLocalDayStaysThere() {
        ZoneId zone = ZoneId.systemDefault();
        LocalDate today = LocalDate.now(zone);
        toolCall(today.atStartOfDay(zone).minusMinutes(30));

        List<Map<String, Object>> items = itemsOf(controller.timeseries(7));

        assertThat(items.get(5).get("date")).isEqualTo(today.minusDays(1).toString());
        assertThat(items.get(5).get("toolCalls")).isEqualTo(1L);
        assertThat(items.get(6).get("toolCalls")).isEqualTo(0L);
    }

    @Test
    @DisplayName("하루에 흩어진 호출은 한 칸으로 합산된다 — UTC 시각별로 쪼개지지 않는다")
    void hoursOfOneLocalDayAreSummed() {
        ZoneId zone = ZoneId.systemDefault();
        ZonedDateTime midnight = LocalDate.now(zone).atStartOfDay(zone);
        toolCall(midnight.plusHours(1));
        toolCall(midnight.plusHours(11));
        toolCall(midnight.plusHours(23));

        List<Map<String, Object>> items = itemsOf(controller.timeseries(7));

        assertThat(items.get(6).get("toolCalls")).isEqualTo(3L);
    }

    @Test
    @DisplayName("데이터가 없는 날도 0 으로 채워 축이 끊기지 않는다")
    void emptyDaysAreFilledWithZero() {
        List<Map<String, Object>> items = itemsOf(controller.timeseries(3));

        assertThat(items).hasSize(3);
        assertThat(items).allSatisfy(row -> {
            assertThat(row.get("toolCalls")).isEqualTo(0L);
            assertThat(row.get("sessions")).isEqualTo(0L);
            assertThat(row.get("events")).isEqualTo(0L);
        });
    }

    @Test
    @DisplayName("세션과 이벤트도 같은 로컬 날짜 칸을 쓴다")
    void sessionsAndEventsShareTheAxis() {
        ZoneId zone = ZoneId.systemDefault();
        ZonedDateTime midnight = LocalDate.now(zone).atStartOfDay(zone);
        jdbc.update("INSERT INTO session (started_at) VALUES (?)",
                Times.of(midnight.plusMinutes(10).toInstant()));
        jdbc.update("INSERT INTO usage_event (event_uid, received_at, kind, payload)"
                        + " VALUES (?, ?, 'voice', '{}')",
                UUID.randomUUID().toString(), Times.of(midnight.plusMinutes(20).toInstant()));

        List<Map<String, Object>> items = itemsOf(controller.timeseries(7));

        assertThat(items.get(6).get("sessions")).isEqualTo(1L);
        assertThat(items.get(6).get("events")).isEqualTo(1L);
    }

    private void toolCall(ZonedDateTime at) {
        jdbc.update("INSERT INTO tool (name, description, input_schema_json, synced_at)"
                + " VALUES ('window.focus', 'd', '{}', ?) ON CONFLICT(name) DO NOTHING",
                Times.now());
        jdbc.update("INSERT INTO tool_call (tool_name, ts, args_json, caller, outcome)"
                        + " VALUES ('window.focus', ?, '{}', 'LLM', 'EXECUTED')",
                Times.of(at.toInstant()));
    }

    @SuppressWarnings("unchecked")
    private static List<Map<String, Object>> itemsOf(Map<String, Object> body) {
        return (List<Map<String, Object>>) body.get("items");
    }
}
