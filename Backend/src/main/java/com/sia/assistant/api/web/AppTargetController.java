package com.sia.assistant.api.web;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.JsonBody;
import com.sia.assistant.common.Times;
import com.sia.assistant.control.process.AppScanService;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * app.launch 화이트리스트(app_target) 관리 — 사용자가 등록한 것(개별 POST 또는 스캔 일괄 등록)과
 * BE 가 시드한 Windows 기본 앱(DefaultAppTargets: 메모장·계산기)만 실행된다.
 * appKey 는 [a-z0-9_-]{1,40}. POST /api/apps 는 같은 appKey 가 있으면 갱신(UPSERT)이다.
 */
@RestController
@RequestMapping("/api/apps")
public class AppTargetController {

    private final ObjectMapper om;

    private static final Pattern APP_KEY = Pattern.compile("^[a-z0-9_-]{1,40}$");

    private final JdbcTemplate jdbc;
    private final AppScanService appScanService;

    public AppTargetController(JdbcTemplate jdbc, AppScanService appScanService, ObjectMapper om) {
        this.om = om;
        this.jdbc = jdbc;
        this.appScanService = appScanService;
    }

    /**
     * 설치 앱 스캔 — 시작 메뉴 .lnk 기반 등록 후보 목록 (DB 에 쓰지 않는다).
     * 각 항목: {name, execPath, args, suggestedKey, registered, appKey?}. 골라서 등록할 때는 POST /api/apps 로.
     */
    @GetMapping("/scan")
    public List<Map<String, Object>> scan() {
        return appScanService.scan();
    }

    /**
     * 스캔 결과 일괄 등록 — 아직 등록되지 않은 실행 파일을 전부 app_target 에 넣는다
     * (최초 실행 온보딩에서 FE 가 1회 호출). 본문 없음.
     * 반환 {scanned, registered, skipped, items} — items 는 이번에 등록된 행(GET /api/apps 행 형식).
     * 다시 호출하면 새로 설치된 앱만 추가된다.
     */
    @PostMapping("/scan")
    public Map<String, Object> scanAndRegister() {
        AppScanService.RegisterResult result = appScanService.scanAndRegister();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("scanned", result.scanned());
        out.put("registered", result.registered());
        out.put("skipped", result.skipped());
        out.put("items", result.items());
        return out;
    }

    @GetMapping
    public List<Map<String, Object>> list() {
        return jdbc.query("SELECT id, app_key, display_name, exec_path, args, verified_at, enabled"
                + " FROM app_target ORDER BY app_key", (rs, i) -> row(
                rs.getLong("id"), rs.getString("app_key"), rs.getString("display_name"),
                rs.getString("exec_path"), rs.getString("args"),
                rs.getString("verified_at"), rs.getInt("enabled") == 1));
    }

    @PostMapping
    public Map<String, Object> upsert(@RequestBody String rawBody) {
        JsonNode body = JsonBody.parse(om, rawBody);
        String appKey = text(body, "appKey");
        String displayName = text(body, "displayName");
        String execPath = text(body, "execPath");
        String args = body.hasNonNull("args") ? body.get("args").asText() : "";
        boolean enabled = body.path("enabled").asBoolean(true);

        if (appKey == null || !APP_KEY.matcher(appKey).matches()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "appKey 는 영문 소문자·숫자·하이픈·언더스코어 1~40자여야 합니다");
        }
        if (displayName == null || displayName.isBlank()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "표시 이름(displayName)이 필요합니다");
        }
        if (execPath == null || execPath.isBlank()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "실행 파일 경로(execPath)가 필요합니다");
        }
        String verifiedAt = pathExists(execPath) ? Times.now() : null;

        // app_key UNIQUE 라 UPSERT 가 안전하고, id 는 키로 되읽는다 (풀 커넥션이 바뀌어도 무관)
        jdbc.update("INSERT INTO app_target (app_key, display_name, exec_path, args, verified_at, enabled)"
                        + " VALUES (?, ?, ?, ?, ?, ?)"
                        + " ON CONFLICT(app_key) DO UPDATE SET display_name = excluded.display_name,"
                        + " exec_path = excluded.exec_path, args = excluded.args,"
                        + " verified_at = excluded.verified_at, enabled = excluded.enabled",
                appKey, displayName, execPath, args, verifiedAt, enabled ? 1 : 0);
        Long id = jdbc.queryForObject("SELECT id FROM app_target WHERE app_key = ?", Long.class, appKey);
        return row(id, appKey, displayName, execPath, args, verifiedAt, enabled);
    }

    @DeleteMapping("/{appKey}")
    public ResponseEntity<Void> delete(@PathVariable String appKey) {
        int deleted = jdbc.update("DELETE FROM app_target WHERE app_key = ?", appKey);
        if (deleted == 0) {
            throw new ApiException(ErrorCode.NOT_FOUND, "등록되지 않은 앱입니다: " + appKey);
        }
        return ResponseEntity.noContent().build();
    }

    /**
     * 경로 검증. {"appKey": "..."} 면 등록된 행을 검사해 verified_at 을 갱신하고,
     * {"execPath": "..."} 면 등록 전 경로만 확인해 준다.
     */
    @PostMapping("/verify")
    public Map<String, Object> verify(@RequestBody String rawBody) {
        JsonNode body = JsonBody.parse(om, rawBody);
        String appKey = text(body, "appKey");
        if (appKey == null || appKey.isBlank()) {
            String execPath = text(body, "execPath");
            if (execPath == null || execPath.isBlank()) {
                throw new ApiException(ErrorCode.INVALID_REQUEST, "appKey 또는 execPath 가 필요합니다");
            }
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("execPath", execPath);
            out.put("exists", pathExists(execPath));
            return out;
        }
        String execPath = jdbc.query("SELECT exec_path FROM app_target WHERE app_key = ?",
                (rs, i) -> rs.getString(1), appKey).stream().findFirst()
                .orElseThrow(() -> new ApiException(ErrorCode.NOT_FOUND, "등록되지 않은 앱입니다: " + appKey));
        boolean exists = pathExists(execPath);
        String verifiedAt = exists ? Times.now() : null;
        jdbc.update("UPDATE app_target SET verified_at = ? WHERE app_key = ?", verifiedAt, appKey);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("appKey", appKey);
        out.put("exists", exists);
        out.put("verifiedAt", verifiedAt);
        return out;
    }

    private static boolean pathExists(String execPath) {
        try {
            return Files.exists(Path.of(execPath));
        } catch (InvalidPathException e) {
            return false;
        }
    }

    private static String text(JsonNode body, String field) {
        return body != null && body.hasNonNull(field) ? body.get(field).asText() : null;
    }

    private static Map<String, Object> row(long id, String appKey, String displayName, String execPath,
                                           String args, String verifiedAt, boolean enabled) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", id);
        out.put("appKey", appKey);
        out.put("displayName", displayName);
        out.put("execPath", execPath);
        out.put("args", args);
        out.put("verifiedAt", verifiedAt);
        out.put("enabled", enabled);
        return out;
    }
}
