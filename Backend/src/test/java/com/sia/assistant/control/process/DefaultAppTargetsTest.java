package com.sia.assistant.control.process;

import static org.assertj.core.api.Assertions.assertThat;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

/**
 * Windows 기본 앱 시드 규칙 — 없는 키만 넣고, 기존 등록(키·경로·enabled)은 건드리지 않는다.
 * 실제 %SystemRoot% 경로에 의존하지 않도록 후보 경로는 임시 디렉터리로 넘긴다.
 */
class DefaultAppTargetsTest {

    private SingleConnectionDataSource ds;
    private JdbcTemplate jdbc;
    private Path apps;

    @BeforeEach
    void setUp(@TempDir Path dir) throws IOException {
        ds = new SingleConnectionDataSource("jdbc:sqlite:" + dir.resolve("builtins-test.db"), true);
        Flyway.configure().dataSource(ds).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(ds);
        apps = Files.createDirectories(dir.resolve("System32"));
    }

    @AfterEach
    void tearDown() {
        ds.destroy();
    }

    @Test
    @DisplayName("빈 테이블에는 기본 앱이 전부 들어간다 — enabled=1, args 없음, verified_at 은 확인 시각")
    void seedsEveryBuiltinIntoEmptyTable() throws IOException {
        int seeded = DefaultAppTargets.seedInto(jdbc, List.of(
                builtin("notepad", "메모장", exe("notepad.exe")),
                builtin("calc", "계산기", exe("calc.exe"))));

        assertThat(seeded).isEqualTo(2);
        assertThat(jdbc.queryForList("SELECT app_key, display_name, args, verified_at, enabled"
                + " FROM app_target ORDER BY app_key"))
                .extracting(row -> row.get("app_key")).containsExactly("calc", "notepad");
        assertThat(jdbc.queryForList("SELECT args, verified_at, enabled FROM app_target"))
                .allSatisfy(row -> {
                    assertThat(row).containsEntry("args", "").containsEntry("enabled", 1);
                    assertThat((String) row.get("verified_at")).hasSize(23);
                });
    }

    @Test
    @DisplayName("같은 키가 이미 있으면 손대지 않는다 — 사용자가 고친 경로·표시 이름·enabled 가 남는다")
    void keepsExistingRowWithSameKey() throws IOException {
        String notepadPlus = exe("notepad++.exe");
        jdbc.update("INSERT INTO app_target (app_key, display_name, exec_path, args, enabled)"
                + " VALUES ('notepad', 'Notepad++', ?, '-multiInst', 0)", notepadPlus);

        int seeded = DefaultAppTargets.seedInto(jdbc, List.of(
                builtin("notepad", "메모장", exe("notepad.exe"))));

        assertThat(seeded).isZero();
        Map<String, Object> row = jdbc.queryForMap("SELECT display_name, exec_path, args, enabled"
                + " FROM app_target WHERE app_key = 'notepad'");
        assertThat(row).containsEntry("display_name", "Notepad++")
                .containsEntry("exec_path", notepadPlus)
                .containsEntry("args", "-multiInst")
                .containsEntry("enabled", 0);
    }

    @Test
    @DisplayName("같은 실행 파일이 다른 키로 등록돼 있으면 넣지 않는다 — 경로 비교는 대소문자 무시")
    void skipsExecPathAlreadyRegisteredUnderAnotherKey() throws IOException {
        String notepad = exe("notepad.exe");
        jdbc.update("INSERT INTO app_target (app_key, display_name, exec_path, args, enabled)"
                + " VALUES ('memo', '메모', ?, '', 1)", notepad.toUpperCase());

        int seeded = DefaultAppTargets.seedInto(jdbc, List.of(builtin("notepad", "메모장", notepad)));

        assertThat(seeded).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM app_target", Integer.class)).isEqualTo(1);
    }

    @Test
    @DisplayName("실행 파일이 없는 항목은 건너뛴다 — verified_at 이 null 인 행을 만들지 않는다")
    void skipsBuiltinWithoutExecutable() {
        int seeded = DefaultAppTargets.seedInto(jdbc, List.of(
                builtin("calc", "계산기", apps.resolve("calc.exe").toString())));

        assertThat(seeded).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM app_target", Integer.class)).isZero();
    }

    @Test
    @DisplayName("후보 경로 중 실재하는 첫 경로를 쓴다")
    void usesFirstExistingCandidate() throws IOException {
        String fallback = exe("notepad.exe");

        int seeded = DefaultAppTargets.seedInto(jdbc, List.of(new DefaultAppTargets.Builtin(
                "notepad", "메모장", List.of(apps.resolve("missing.exe").toString(), fallback))));

        assertThat(seeded).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT exec_path FROM app_target WHERE app_key = 'notepad'",
                String.class)).isEqualTo(fallback);
    }

    @Test
    @DisplayName("기본 앱 목록은 메모장·계산기 두 건이고 경로는 %SystemRoot% 기준이다")
    void listsNotepadAndCalculator() {
        List<DefaultAppTargets.Builtin> all = DefaultAppTargets.all();

        assertThat(all).extracting(DefaultAppTargets.Builtin::appKey).containsExactly("notepad", "calc");
        assertThat(all).extracting(DefaultAppTargets.Builtin::displayName).containsExactly("메모장", "계산기");
        // 경로 앞머리는 %SystemRoot% 원문이라 대소문자를 단정하지 않는다 (C:\WINDOWS 로 오는 환경이 있다)
        assertThat(all.get(0).candidates()).first().asString().endsWith("\\System32\\notepad.exe");
        assertThat(all.get(1).candidates()).singleElement().asString().endsWith("\\System32\\calc.exe");
    }

    private String exe(String fileName) throws IOException {
        return Files.createFile(apps.resolve(fileName)).toString();
    }

    private static DefaultAppTargets.Builtin builtin(String appKey, String displayName, String execPath) {
        return new DefaultAppTargets.Builtin(appKey, displayName, List.of(execPath));
    }
}
