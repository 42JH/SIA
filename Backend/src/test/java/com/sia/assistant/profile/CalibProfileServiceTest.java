package com.sia.assistant.profile;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.sia.assistant.relay.AgentSyncNotifier;
import com.sia.assistant.ws.AgentHub;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

/**
 * 보정 프로필의 오차 등급(grade)과 산점도 왕복 — V2__calib_grade.sql 의 ADD COLUMN 이 실제
 * SQLite 에 먹는지, 목록·상세가 grade 를 되돌려주는지 본다.
 * 등급 판정 기준은 AI 서버 소관이라 BE 는 받아 적기만 하고 통과 여부를 계산하지 않는다.
 */
class CalibProfileServiceTest {

    private static final String POINTS = "[{\"n\":1,\"dx\":11,\"dy\":12}]";

    private SingleConnectionDataSource ds;
    private JdbcTemplate jdbc;
    private CalibProfileService service;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp(@TempDir Path dir) {
        // 단일 커넥션 — saveNew 가 INSERT 직후 last_insert_rowid() 를 같은 커넥션에서 읽어야 한다
        // (운영은 @Transactional 이 커넥션을 고정한다).
        ds = new SingleConnectionDataSource("jdbc:sqlite:" + dir.resolve("calibs-test.db"), true);
        Flyway.configure().dataSource(ds).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(ds);
        ObjectProvider<AgentSyncNotifier> notifierProvider = mock(ObjectProvider.class);
        when(notifierProvider.getIfAvailable()).thenReturn(mock(AgentSyncNotifier.class));
        service = new CalibProfileService(jdbc, mock(AgentHub.class), notifierProvider);
    }

    @AfterEach
    void tearDown() {
        ds.destroy();
    }

    @Test
    @DisplayName("목록·상세는 오차 등급과 dx/dy 산점도를 되돌려주고 통과 기준은 싣지 않는다")
    void gradeAndPointsRoundTrip() {
        long id = service.saveNew(null, new byte[]{1}, "sha", 1920, 1080, 38.0, 62.0,
                "good", POINTS, "HD Webcam");

        List<Map<String, Object>> items = service.list();
        assertThat(items).hasSize(1);
        assertThat(items.get(0))
                .containsEntry("name", "내 보정 1")
                .containsEntry("avgErrorPx", 38.0)
                .containsEntry("grade", "good")
                .doesNotContainKeys("thresholdPx", "pass");
        assertThat(service.get(id))
                .containsEntry("grade", "good")
                .containsEntry("pointsJson", POINTS);
    }

    @Test
    @DisplayName("등급은 세 값만 들어간다 — V2 의 CHECK 가 엉뚱한 값을 막는다")
    void gradeCheckRejectsUnknownValue() {
        long id = service.saveNew(null, new byte[]{1}, "sha", 1920, 1080, 38.0, 62.0,
                "poor", POINTS, "HD Webcam");

        assertThatThrownBy(() -> jdbc.update(
                "UPDATE calib_profile SET grade = 'terrible' WHERE id = ?", id))
                .hasMessageContaining("CHECK constraint failed: grade");
    }
}
