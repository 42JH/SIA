package com.sia.assistant.api.web;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 도구 사전 조회 (GET /api/tools).
 * 기본은 이번 기동에 등록된(available=1) 것만, all=true 면 빠진 행까지 전부.
 */
@RestController
public class ToolController {

    private final JdbcTemplate jdbc;

    public ToolController(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @GetMapping("/api/tools")
    public List<Map<String, Object>> list(@RequestParam(name = "all", defaultValue = "false") boolean all) {
        String sql = "SELECT name, description, session_required, confirm_required, available, synced_at"
                + " FROM tool" + (all ? "" : " WHERE available = 1") + " ORDER BY name";
        return jdbc.query(sql, (rs, i) -> {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("name", rs.getString("name"));
            row.put("description", rs.getString("description"));
            row.put("sessionRequired", rs.getInt("session_required") == 1);
            row.put("confirmRequired", rs.getInt("confirm_required") == 1);
            row.put("available", rs.getInt("available") == 1);
            row.put("syncedAt", rs.getString("synced_at"));
            return row;
        });
    }
}
