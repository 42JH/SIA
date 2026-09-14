package com.sia.assistant.settings;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Path;
import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationVersion;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;

/**
 * V4__wakeword_default.sql — 호출어 초기값을 "시아야" 로 올리되 사용자가 고른 값은 덮지 않는다.
 *
 * <p>초기값 한 글자를 바꾸는 마이그레이션이라 무해해 보이지만 위험한 쪽은 반대다: 조건 없이
 * UPDATE 하면 이미 자기 호출어를 정해 둔 DB 를 조용히 되돌린다. 그 조건({@code settings_version = 1})이
 * 실제로 지켜지는지를 진짜 Flyway · 진짜 SQLite 로 확인한다.
 */
class WakewordDefaultMigrationTest {

    private static DriverManagerDataSource dataSource(Path dir) {
        return new DriverManagerDataSource("jdbc:sqlite:" + dir.resolve("wakeword-migration-test.db"));
    }

    /** target 버전까지만 올린다. null 이면 최신까지. */
    private static void migrate(DriverManagerDataSource ds, String target) {
        Flyway.configure()
                .dataSource(ds)
                .locations("classpath:db/migration")
                .target(target == null ? MigrationVersion.LATEST : MigrationVersion.fromVersion(target))
                .load()
                .migrate();
    }

    private static String wakeWord(DriverManagerDataSource ds) {
        return new JdbcTemplate(ds).queryForObject(
                "SELECT json_extract(settings_json, '$.wakeWord') FROM app_settings WHERE id = 1", String.class);
    }

    @Test
    @DisplayName("새 DB 의 초기 호출어는 시아야 다")
    void freshDatabaseGetsNewDefault(@TempDir Path dir) {
        DriverManagerDataSource ds = dataSource(dir);

        migrate(ds, null);

        assertThat(wakeWord(ds)).isEqualTo("시아야");
        // 저장한 적 없는 초기 상태 그대로여야 한다 — 버전이 오르면 FE 에 까닭 없는 settingsPending 이 뜬다
        assertThat(new JdbcTemplate(ds).queryForObject(
                "SELECT settings_version FROM app_settings WHERE id = 1", Integer.class)).isEqualTo(1);
    }

    @Test
    @DisplayName("사용자가 저장한 호출어는 V4 가 덮지 않는다")
    void savedWakeWordSurvivesMigration(@TempDir Path dir) {
        DriverManagerDataSource ds = dataSource(dir);
        migrate(ds, "3");   // V4 직전 — 아직 초기값이 "시아" 인 기존 DB
        new JdbcTemplate(ds).update(
                "UPDATE app_settings SET settings_json = json_set(settings_json, '$.wakeWord', '비서야'),"
                        + " settings_version = 2 WHERE id = 1");

        migrate(ds, null);

        assertThat(wakeWord(ds)).isEqualTo("비서야");
    }
}
