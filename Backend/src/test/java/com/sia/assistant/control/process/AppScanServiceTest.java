package com.sia.assistant.control.process;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;

import com.sia.assistant.control.com.ComWorker;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
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
import org.springframework.jdbc.support.JdbcTransactionManager;

/**
 * POST /api/apps/scan 의 일괄 등록 규칙 — 미등록 실행 파일만 넣고, 기존 등록(키·경로)은 건드리지 않는다.
 * 스캔 자체(COM)는 여기서 돌리지 않고 scan() 형식의 후보 목록을 직접 넘긴다.
 */
class AppScanServiceTest {

    private SingleConnectionDataSource ds;
    private JdbcTemplate jdbc;
    private AppScanService service;
    private Path apps;

    @BeforeEach
    void setUp(@TempDir Path dir) throws IOException {
        // 단일 커넥션 — register() 가 INSERT 직후 같은 트랜잭션에서 id 를 되읽는다
        ds = new SingleConnectionDataSource("jdbc:sqlite:" + dir.resolve("apps-test.db"), true);
        Flyway.configure().dataSource(ds).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(ds);
        service = new AppScanService(mock(ComWorker.class), jdbc, new JdbcTransactionManager(ds));
        apps = Files.createDirectories(dir.resolve("apps"));
    }

    @AfterEach
    void tearDown() {
        ds.destroy();
    }

    @Test
    @DisplayName("미등록 후보는 전부 등록된다 — enabled=1, verified_at 은 실재 확인 시각")
    void registersEveryUnregisteredCandidate() throws IOException {
        String code = exe("Code.exe");
        String kakao = exe("KakaoTalk.exe");

        AppScanService.RegisterResult r = service.register(List.of(
                candidate("Visual Studio Code", code, "visual-studio-code"),
                candidate("카카오톡", kakao, "kakaotalk")));

        assertThat(r.scanned()).isEqualTo(2);
        assertThat(r.registered()).isEqualTo(2);
        assertThat(r.skipped()).isZero();
        assertThat(r.items()).extracting(m -> m.get("appKey"))
                .containsExactly("visual-studio-code", "kakaotalk");
        assertThat(r.items()).allSatisfy(m -> {
            assertThat(m.get("id")).isNotNull();
            assertThat(m.get("enabled")).isEqualTo(true);
            assertThat((String) m.get("verifiedAt")).hasSize(23);
        });
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM app_target WHERE enabled = 1", Integer.class))
                .isEqualTo(2);
    }

    @Test
    @DisplayName("이미 등록된 실행 파일은 건너뛴다 — 경로 비교는 대소문자 무시, 기존 행은 그대로")
    void skipsAlreadyRegisteredExecPath() throws IOException {
        String chrome = exe("chrome.exe");
        jdbc.update("INSERT INTO app_target (app_key, display_name, exec_path, args, enabled)"
                + " VALUES ('browser', '내 브라우저', ?, '', 1)", chrome.toUpperCase());

        AppScanService.RegisterResult r = service.register(List.of(
                candidate("Google Chrome", chrome, "google-chrome")));

        assertThat(r.registered()).isZero();
        assertThat(r.skipped()).isEqualTo(1);
        assertThat(r.items()).isEmpty();
        assertThat(jdbc.queryForList("SELECT app_key, display_name FROM app_target"))
                .singleElement()
                .satisfies(row -> assertThat(row)
                        .containsEntry("app_key", "browser")
                        .containsEntry("display_name", "내 브라우저"));
    }

    @Test
    @DisplayName("suggestedKey 가 기존 키와 겹치면 -2 를 붙인다 — 사용자 등록을 덮어쓰지 않는다")
    void suffixesKeyThatCollidesWithExistingRegistration() throws IOException {
        String oldChrome = exe("old-chrome.exe");
        String newChrome = exe("new-chrome.exe");
        jdbc.update("INSERT INTO app_target (app_key, display_name, exec_path, args, enabled)"
                + " VALUES ('chrome', 'Chrome (수동)', ?, '--kiosk', 1)", oldChrome);

        AppScanService.RegisterResult r = service.register(List.of(candidate("Chrome", newChrome, "chrome")));

        assertThat(r.registered()).isEqualTo(1);
        assertThat(r.items().get(0)).containsEntry("appKey", "chrome-2");
        Map<String, Object> manual = jdbc.queryForMap("SELECT exec_path, args FROM app_target WHERE app_key = 'chrome'");
        assertThat(manual).containsEntry("exec_path", oldChrome).containsEntry("args", "--kiosk");
    }

    @Test
    @DisplayName("다시 호출하면 새로 설치된 앱만 추가된다")
    void secondRunAddsOnlyNewApps() throws IOException {
        String a = exe("a.exe");
        String b = exe("b.exe");
        service.register(List.of(candidate("A", a, "a")));

        AppScanService.RegisterResult r = service.register(List.of(
                candidate("A", a, "a"), candidate("B", b, "b")));

        assertThat(r.scanned()).isEqualTo(2);
        assertThat(r.registered()).isEqualTo(1);
        assertThat(r.skipped()).isEqualTo(1);
        assertThat(r.items()).singleElement().satisfies(m -> assertThat(m).containsEntry("appKey", "b"));
    }

    @Test
    @DisplayName("실행 파일이 실재하지 않으면 verified_at 이 null 이다 (POST /api/apps 와 같은 규칙)")
    void missingExecutableLeavesVerifiedAtNull() {
        AppScanService.RegisterResult r = service.register(List.of(
                candidate("Ghost", apps.resolve("ghost.exe").toString(), "ghost")));

        assertThat(r.registered()).isEqualTo(1);
        assertThat(r.items().get(0).get("verifiedAt")).isNull();
    }

    private String exe(String fileName) throws IOException {
        return Files.createFile(apps.resolve(fileName)).toString();
    }

    private static Map<String, Object> candidate(String name, String execPath, String suggestedKey) {
        Map<String, Object> row = new LinkedHashMap<>();
        row.put("name", name);
        row.put("execPath", execPath);
        row.put("args", "");
        row.put("suggestedKey", suggestedKey);
        row.put("registered", false);
        row.put("appKey", null);
        return row;
    }
}
