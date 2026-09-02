package com.sia.assistant.control.process;

import com.sia.assistant.common.Times;
import java.nio.file.Files;
import java.nio.file.InvalidPathException;
import java.nio.file.Path;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * Windows 기본 앱 시드 — 메모장·계산기. app_target 에 그 키가 없으면 기동 시 넣어 처음부터
 * app.launch 대상이 되게 한다.
 * 스캔(AppScanService)으로는 이 둘이 잡히지 않기 때문이다: Windows 11 의 메모장·계산기는
 * Store(AppX) 앱이라 시작 메뉴에 .lnk 가 없어 후보 목록에 아예 오르지 않는다. 그래도 실행 파일
 * 자체는 %SystemRoot%\System32 에 있어 ProcessBuilder 로 그대로 띄울 수 있다
 * (calc.exe 는 Store 계산기를 띄우고 바로 끝나는 런처라 pid 가 곧 죽는다 — AppLaunchService 의
 * "pid 는 참고값" 주석 그대로, 창 조작은 pid 가 아니라 context.get 의 ref 로 한다).
 *
 * 규칙 — DefaultMappings 와 같은 결이지만 "테이블이 비어 있을 때만" 이 아니라 "없는 키만" 이다:
 *  - app_key 가 이미 있으면 손대지 않는다 (사용자가 경로·표시 이름·enabled 를 고쳤을 수 있다).
 *  - 같은 실행 파일이 다른 키로 등록돼 있으면 넣지 않는다 (AppScanService.register 와 같은 중복 규칙).
 *  - 실행 파일이 실재하지 않으면 그 항목은 건너뛴다 — verified_at 이 null 인 행을 만들지 않는다.
 *  - 목록에서 빼려면 DELETE 가 아니라 enabled = 0 이다. 지우면 다음 기동에 다시 살아난다.
 * exec_path 는 여기서도 BE 가 정한다 — LLM 이 경로를 채우는 칸은 여전히 없다.
 */
public final class DefaultAppTargets {

    /** candidates = 후보 경로. 실재하는 첫 경로를 쓴다 (빌드에 따라 메모장이 %SystemRoot% 직하에만 있다). */
    record Builtin(String appKey, String displayName, List<String> candidates) {
    }

    static List<Builtin> all() {
        String root = systemRoot();
        return List.of(
                new Builtin("notepad", "메모장",
                        List.of(root + "\\System32\\notepad.exe", root + "\\notepad.exe")),
                new Builtin("calc", "계산기",
                        List.of(root + "\\System32\\calc.exe")));
    }

    /** 없는 키만 넣는다. 호출자가 트랜잭션을 보장한다. 반환 = 이번에 넣은 건수. */
    public static int seedInto(JdbcTemplate jdbc) {
        return seedInto(jdbc, all());
    }

    static int seedInto(JdbcTemplate jdbc, List<Builtin> builtins) {
        Set<String> registeredPaths = new HashSet<>();
        jdbc.query("SELECT exec_path FROM app_target", rs -> {
            registeredPaths.add(rs.getString("exec_path").toLowerCase(Locale.ROOT));
        });

        int inserted = 0;
        for (Builtin builtin : builtins) {
            String execPath = firstExisting(builtin.candidates());
            if (execPath == null || registeredPaths.contains(execPath.toLowerCase(Locale.ROOT))) {
                continue;
            }
            // 키가 이미 있으면 IGNORE — 사용자가 같은 키로 등록한 행을 덮지 않는다
            int rows = jdbc.update(
                    "INSERT OR IGNORE INTO app_target (app_key, display_name, exec_path, args, verified_at, enabled)"
                            + " VALUES (?, ?, ?, '', ?, 1)",
                    builtin.appKey(), builtin.displayName(), execPath, Times.now());
            if (rows > 0) {
                registeredPaths.add(execPath.toLowerCase(Locale.ROOT));
                inserted += rows;
            }
        }
        return inserted;
    }

    private static String firstExisting(List<String> candidates) {
        for (String candidate : candidates) {
            try {
                if (Files.exists(Path.of(candidate))) {
                    return candidate;
                }
            } catch (InvalidPathException e) {
                // 다음 후보로
            }
        }
        return null;
    }

    /** %SystemRoot% (없으면 %windir%, 그것도 없으면 관례값). 끝의 구분자는 떼고 돌려준다. */
    private static String systemRoot() {
        String root = System.getenv("SystemRoot");
        if (root == null || root.isBlank()) {
            root = System.getenv("windir");
        }
        if (root == null || root.isBlank()) {
            root = "C:\\Windows";
        }
        return root.replaceAll("[\\\\/]+$", "");
    }

    private DefaultAppTargets() {
    }
}
