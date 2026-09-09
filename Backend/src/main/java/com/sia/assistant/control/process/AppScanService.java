package com.sia.assistant.control.process;

import com.sia.assistant.common.Times;
import com.sia.assistant.control.com.ComWorker;
import com.sia.assistant.control.com.LateDispatch;
import com.sun.jna.platform.win32.Variant;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Stream;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * 설치 앱 스캔 — 시작 메뉴 .lnk 를 열거해 app_target 등록 후보를 만든다.
 *  - GET  /api/apps/scan : 후보 목록만 돌려준다 (DB 에 쓰지 않는다). 항목을 골라 등록하는 화면용.
 *  - POST /api/apps/scan : 후보 중 아직 등록되지 않은 실행 파일을 전부 app_target 에 넣는다 —
 *    최초 실행 온보딩에서 FE 가 1회 호출해 설치된 앱을 한 번에 실행 가능 앱으로 만든다.
 * 어느 경로든 등록의 주체는 사용자(FE)이고 exec_path 는 LLM 에게 주지 않는다
 * (MCP 도구가 아니라 FE 전용 REST 인 이유 — V1 스키마 주석 "LLM 이 채우는 칸이 아니다" 유지).
 */
@Service
public class AppScanService {

    private static final Logger log = LoggerFactory.getLogger(AppScanService.class);

    private static final int MAX_RESULTS = 200;
    private static final int MAX_LNK = 600;
    private static final Pattern EXCLUDE_NAME =
            Pattern.compile("(?i)(uninstall|uninst|remove|제거|설치\\s*제거|updater|repair|readme|help|manual)");

    private final ComWorker comWorker;
    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;

    public AppScanService(ComWorker comWorker, JdbcTemplate jdbc, PlatformTransactionManager txManager) {
        this.comWorker = comWorker;
        this.jdbc = jdbc;
        this.tx = new TransactionTemplate(txManager);
    }

    /** POST /api/apps/scan 의 결과. items 는 이번 호출로 새로 등록된 행 — GET /api/apps 행과 같은 형식. */
    public record RegisterResult(int scanned, int registered, int skipped, List<Map<String, Object>> items) {
    }

    public List<Map<String, Object>> scan() {
        List<Path> links = collectLinks();
        Map<Path, String[]> resolved = comWorker.call("바로가기 해석", 20000, () -> resolveAll(links));

        // 이미 등록된 exec_path → appKey (등록 여부 표시용)
        Map<String, String> registered = new HashMap<>();
        jdbc.query("SELECT app_key, exec_path FROM app_target", rs -> {
            registered.put(rs.getString("exec_path").toLowerCase(Locale.ROOT), rs.getString("app_key"));
        });

        Set<String> seenTargets = new HashSet<>();
        Set<String> usedKeys = new HashSet<>();
        List<Map<String, Object>> out = new ArrayList<>();
        for (Path lnk : links) {
            String[] target = resolved.get(lnk);
            if (target == null) {
                continue;
            }
            String execPath = target[0];
            String args = target[1] == null ? "" : target[1];
            if (execPath == null || execPath.isBlank()
                    || !execPath.toLowerCase(Locale.ROOT).endsWith(".exe")
                    || !safeExists(execPath)) {
                continue;
            }
            if (!seenTargets.add(execPath.toLowerCase(Locale.ROOT))) {
                continue; // 같은 실행 파일을 가리키는 바로가기 중복 제거
            }
            String name = stem(lnk.getFileName().toString());
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("name", name);
            row.put("execPath", execPath);
            row.put("args", args);
            row.put("suggestedKey", uniqueKey(suggestKey(name, execPath), usedKeys));
            String appKey = registered.get(execPath.toLowerCase(Locale.ROOT));
            row.put("registered", appKey != null);
            row.put("appKey", appKey);
            out.add(row);
            if (out.size() >= MAX_RESULTS) {
                break;
            }
        }
        out.sort(Comparator.comparing(r -> String.valueOf(r.get("name")), String.CASE_INSENSITIVE_ORDER));
        return out;
    }

    /** 스캔 후 아직 등록되지 않은 실행 파일을 전부 등록한다 (POST /api/apps/scan). */
    public RegisterResult scanAndRegister() {
        return register(scan());
    }

    /**
     * 후보 목록(scan() 형식: name, execPath, args, suggestedKey)을 일괄 등록한다. 한 트랜잭션.
     *  - exec_path 가 이미 등록돼 있으면(대소문자 무시) 건너뛰고 skipped 로 센다. 기존 행은 고치지 않는다.
     *  - appKey 는 suggestedKey 를 쓰되 기존 키와 겹치면 -2, -3 … 을 붙인다 (사용자 등록을 덮지 않는다).
     *  - enabled = 1, verified_at 은 실행 파일이 실재하면 지금 시각.
     */
    public RegisterResult register(List<Map<String, Object>> candidates) {
        return tx.execute(status -> {
            Set<String> existingPaths = new HashSet<>();
            Set<String> usedKeys = new HashSet<>();
            jdbc.query("SELECT app_key, exec_path FROM app_target", rs -> {
                usedKeys.add(rs.getString("app_key"));
                existingPaths.add(rs.getString("exec_path").toLowerCase(Locale.ROOT));
            });

            List<Map<String, Object>> items = new ArrayList<>();
            int skipped = 0;
            for (Map<String, Object> candidate : candidates) {
                String execPath = String.valueOf(candidate.get("execPath"));
                if (existingPaths.contains(execPath.toLowerCase(Locale.ROOT))) {
                    skipped++;
                    continue;
                }
                String name = String.valueOf(candidate.get("name"));
                String args = candidate.get("args") == null ? "" : String.valueOf(candidate.get("args"));
                String base = candidate.get("suggestedKey") == null
                        ? suggestKey(name, execPath)
                        : String.valueOf(candidate.get("suggestedKey"));
                String appKey = uniqueKey(base, usedKeys);
                String verifiedAt = safeExists(execPath) ? Times.now() : null;

                // 키는 위에서 유일하게 만들었다 — 동시 호출로 먼저 들어간 행이 있으면 IGNORE 되어 0 이 돌아온다
                int inserted = jdbc.update(
                        "INSERT OR IGNORE INTO app_target (app_key, display_name, exec_path, args, verified_at, enabled)"
                                + " VALUES (?, ?, ?, ?, ?, 1)",
                        appKey, name, execPath, args, verifiedAt);
                if (inserted == 0) {
                    skipped++;
                    continue;
                }
                existingPaths.add(execPath.toLowerCase(Locale.ROOT));
                Long id = jdbc.queryForObject("SELECT id FROM app_target WHERE app_key = ?", Long.class, appKey);

                Map<String, Object> row = new LinkedHashMap<>();
                row.put("id", id);
                row.put("appKey", appKey);
                row.put("displayName", name);
                row.put("execPath", execPath);
                row.put("args", args);
                row.put("verifiedAt", verifiedAt);
                row.put("enabled", true);
                items.add(row);
            }
            log.info("앱 일괄 등록 — 후보 {}건 중 {}건 등록, {}건 건너뜀", candidates.size(), items.size(), skipped);
            return new RegisterResult(candidates.size(), items.size(), skipped, items);
        });
    }

    // ------------------------------------------------------------------ 내부

    /** 시작 메뉴 두 곳(.lnk)을 걷는다 — 시스템 전체 + 현재 사용자. */
    private List<Path> collectLinks() {
        List<Path> out = new ArrayList<>();
        for (String root : startMenuRoots()) {
            Path dir = Path.of(root);
            if (!Files.isDirectory(dir)) {
                continue;
            }
            try (Stream<Path> walk = Files.walk(dir, 4)) {
                walk.filter(Files::isRegularFile)
                        .filter(p -> p.getFileName().toString().toLowerCase(Locale.ROOT).endsWith(".lnk"))
                        .filter(p -> !EXCLUDE_NAME.matcher(stem(p.getFileName().toString())).find())
                        .limit((long) MAX_LNK - out.size())
                        .forEach(out::add);
            } catch (IOException e) {
                log.warn("시작 메뉴 열거 실패: {}", dir, e);
            }
            if (out.size() >= MAX_LNK) {
                break;
            }
        }
        return out;
    }

    private static List<String> startMenuRoots() {
        List<String> roots = new ArrayList<>();
        String programData = System.getenv("ProgramData");
        if (programData != null && !programData.isBlank()) {
            roots.add(programData + "\\Microsoft\\Windows\\Start Menu\\Programs");
        }
        String appData = System.getenv("APPDATA");
        if (appData != null && !appData.isBlank()) {
            roots.add(appData + "\\Microsoft\\Windows\\Start Menu\\Programs");
        }
        return roots;
    }

    /** ComWorker 스레드 전용 — WScript.Shell 하나로 전부 해석한다. 반환: lnk → [TargetPath, Arguments]. */
    private Map<Path, String[]> resolveAll(List<Path> links) {
        Map<Path, String[]> out = new HashMap<>();
        try (LateDispatch wsh = new LateDispatch("WScript.Shell")) {
            for (Path lnk : links) {
                Variant.VARIANT pathArg = LateDispatch.strVariant(lnk.toString());
                try (LateDispatch shortcut = wsh.dispCall("CreateShortcut", pathArg)) {
                    if (shortcut == null) {
                        continue;
                    }
                    out.put(lnk, new String[]{shortcut.strProp("TargetPath"), shortcut.strProp("Arguments")});
                } catch (RuntimeException e) {
                    log.debug("바로가기 해석 실패 {}: {}", lnk, e.toString());
                } finally {
                    LateDispatch.clear(pathArg);
                }
            }
        }
        return out;
    }

    private static boolean safeExists(String path) {
        try {
            return Files.exists(Path.of(path));
        } catch (RuntimeException e) {
            return false;
        }
    }

    private static String stem(String fileName) {
        int dot = fileName.lastIndexOf('.');
        return dot > 0 ? fileName.substring(0, dot) : fileName;
    }

    /** appKey 규칙([a-z0-9_-]{1,40})에 맞춘 제안 — 한글 등은 전부 떨어지므로 그땐 exe 이름으로. */
    private static String suggestKey(String name, String execPath) {
        String key = sanitize(name);
        if (key.isBlank()) {
            String exe = execPath.substring(execPath.lastIndexOf('\\') + 1);
            key = sanitize(stem(exe));
        }
        if (key.isBlank()) {
            key = "app";
        }
        return key.length() > 40 ? key.substring(0, 40) : key;
    }

    private static String sanitize(String raw) {
        String key = raw.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", "-").replaceAll("(^-+|-+$)", "");
        return key.replaceAll("-{2,}", "-");
    }

    private static String uniqueKey(String base, Set<String> used) {
        String key = base;
        int n = 2;
        while (!used.add(key)) {
            String suffix = "-" + n++;
            key = (base.length() + suffix.length() > 40 ? base.substring(0, 40 - suffix.length()) : base) + suffix;
        }
        return key;
    }
}
