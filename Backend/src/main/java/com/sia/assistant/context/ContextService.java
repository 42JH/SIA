package com.sia.assistant.context;

import com.sia.assistant.control.window.WindowService;
import com.sia.assistant.mcp.RefResolver;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

/**
 * 컨텍스트 판정과 context.get 응답 조립.
 * 판정 규칙: 대상 창(지정 또는 포그라운드) 제목에 'youtube'(대소문자 무시) → ["youtube","video"], 그 외 → [].
 * default(제약 없는 매핑)는 조회 측이 마지막에 context IS NULL 로 시도하므로 체인에 싣지 않는다.
 */
@Service
public class ContextService {

    private static final List<String> CAPABILITIES = List.of("window", "scroll", "app", "media", "files");

    private final WindowService windowService;
    private final RefResolver refResolver;
    private final JdbcTemplate jdbc;

    public ContextService(WindowService windowService, RefResolver refResolver, JdbcTemplate jdbc) {
        this.windowService = windowService;
        this.refResolver = refResolver;
        this.jdbc = jdbc;
    }

    /** null 이면 포그라운드 창 기준. 창이 없으면 빈 체인. */
    public List<String> chainFor(Long hwndOrNull) {
        long hwnd = hwndOrNull != null ? hwndOrNull : windowService.foregroundHwnd();
        if (hwnd == 0L) {
            return List.of();
        }
        String title = windowService.titleOf(hwnd);
        if (title.toLowerCase(Locale.ROOT).contains("youtube")) {
            return List.of("youtube", "video");
        }
        return List.of();
    }

    public boolean isYoutube(Long hwndOrNull) {
        return chainFor(hwndOrNull).contains("youtube");
    }

    /** context.get 응답 조립 — 창 스냅샷을 갱신하므로 이 응답의 ref 는 곧바로 유효하다. */
    public Map<String, Object> snapshot() {
        List<Map<String, Object>> windows = refResolver.refreshWindows();

        long fg = windowService.foregroundHwnd();
        Map<String, Object> foreground = null;
        if (fg != 0L) {
            String ref = refResolver.refOf(fg);
            if (ref != null) {
                for (Map<String, Object> w : windows) {
                    if (ref.equals(w.get("ref"))) {
                        foreground = new LinkedHashMap<>();
                        foreground.put("ref", ref);
                        foreground.put("title", w.get("title"));
                        foreground.put("app", w.get("app"));
                        break;
                    }
                }
            }
        }

        List<String> chain = new ArrayList<>(chainFor(fg == 0L ? null : fg));
        chain.add("base");

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("contextChain", chain);
        out.put("foreground", foreground);
        out.put("windows", windows);
        out.put("apps", apps());
        out.put("capabilities", CAPABILITIES);
        return out;
    }

    /** 등록된(enabled) 앱 목록 — app.list 와 snapshot 이 같은 형태로 쓴다. */
    public List<Map<String, Object>> apps() {
        return jdbc.query(
                "SELECT app_key, display_name FROM app_target WHERE enabled = 1 ORDER BY display_name",
                (rs, i) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("ref", "app:" + rs.getString("app_key"));
                    m.put("name", rs.getString("display_name"));
                    return m;
                });
    }
}
