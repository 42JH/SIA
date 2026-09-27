package com.sia.assistant.api.web;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 실행 기록 조회 — GET /api/tool-calls, GET /api/sessions (페이지당 50건, 최신순).
 * from/to 는 UTC 'yyyy-MM-dd HH:mm:ss.SSS' 또는 'yyyy-MM-dd' — 고정폭 문자열 비교로 거른다.
 */
@RestController
public class LogController {

    private static final int PAGE_SIZE = 50;

    private final JdbcTemplate jdbc;

    public LogController(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @GetMapping("/api/tool-calls")
    public Map<String, Object> toolCalls(
            @RequestParam(name = "from", required = false) String from,
            @RequestParam(name = "to", required = false) String to,
            @RequestParam(name = "outcome", required = false) String outcome,
            @RequestParam(name = "caller", required = false) String caller,
            @RequestParam(name = "page", defaultValue = "1") int page) {
        StringBuilder where = new StringBuilder(" WHERE 1=1");
        List<Object> params = new ArrayList<>();
        addRange(where, params, "ts", from, to);
        if (outcome != null && !outcome.isBlank()) {
            where.append(" AND outcome = ?");
            params.add(outcome);
        }
        if (caller != null && !caller.isBlank()) {
            where.append(" AND caller = ?");
            params.add(caller);
        }
        int p = Math.max(1, page);
        Integer total = jdbc.queryForObject("SELECT COUNT(*) FROM tool_call" + where,
                Integer.class, params.toArray());

        List<Object> pageParams = new ArrayList<>(params);
        pageParams.add(PAGE_SIZE);
        pageParams.add((p - 1) * PAGE_SIZE);
        List<Map<String, Object>> items = jdbc.query(
                "SELECT id, session_id, app_target_id, tool_name, ts, args_json, caller, outcome,"
                        + " reason, latency_ms FROM tool_call" + where
                        + " ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
                (rs, i) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("id", rs.getLong("id"));
                    row.put("sessionId", rs.getObject("session_id") == null ? null : rs.getLong("session_id"));
                    row.put("appTargetId", rs.getObject("app_target_id") == null ? null : rs.getLong("app_target_id"));
                    row.put("tool", rs.getString("tool_name"));
                    row.put("ts", rs.getString("ts"));
                    row.put("argsJson", rs.getString("args_json"));
                    row.put("caller", rs.getString("caller"));
                    row.put("outcome", rs.getString("outcome"));
                    row.put("reason", rs.getString("reason"));
                    row.put("latencyMs", rs.getObject("latency_ms") == null ? null : rs.getLong("latency_ms"));
                    return row;
                }, pageParams.toArray());
        return pageBody(p, total, items);
    }

    @GetMapping("/api/sessions")
    public Map<String, Object> sessions(
            @RequestParam(name = "from", required = false) String from,
            @RequestParam(name = "to", required = false) String to,
            @RequestParam(name = "page", defaultValue = "1") int page) {
        StringBuilder where = new StringBuilder(" WHERE 1=1");
        List<Object> params = new ArrayList<>();
        addRange(where, params, "started_at", from, to);
        int p = Math.max(1, page);
        Integer total = jdbc.queryForObject("SELECT COUNT(*) FROM session" + where,
                Integer.class, params.toArray());

        List<Object> pageParams = new ArrayList<>(params);
        pageParams.add(PAGE_SIZE);
        pageParams.add((p - 1) * PAGE_SIZE);
        List<Map<String, Object>> items = jdbc.query(
                "SELECT s.id, s.started_at, s.ended_at, s.end_reason,"
                        + " (SELECT COUNT(*) FROM tool_call tc WHERE tc.session_id = s.id) AS tool_call_count"
                        + " FROM session s" + where
                        + " ORDER BY s.started_at DESC, s.id DESC LIMIT ? OFFSET ?",
                (rs, i) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("id", rs.getLong("id"));
                    row.put("startedAt", rs.getString("started_at"));
                    row.put("endedAt", rs.getString("ended_at"));
                    row.put("endReason", rs.getString("end_reason"));
                    row.put("toolCallCount", rs.getInt("tool_call_count"));
                    return row;
                }, pageParams.toArray());
        return pageBody(p, total, items);
    }

    /** from 은 'yyyy-MM-dd' 면 그 날의 시작, to 는 그 날의 끝으로 넓혀 바인딩한다. */
    private static void addRange(StringBuilder where, List<Object> params,
                                 String column, String from, String to) {
        if (from != null && !from.isBlank()) {
            where.append(" AND ").append(column).append(" >= ?");
            params.add(from.length() == 10 ? from + " 00:00:00.000" : from);
        }
        if (to != null && !to.isBlank()) {
            where.append(" AND ").append(column).append(" <= ?");
            params.add(to.length() == 10 ? to + " 23:59:59.999" : to);
        }
    }

    private static Map<String, Object> pageBody(int page, Integer total, List<Map<String, Object>> items) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("page", page);
        body.put("pageSize", PAGE_SIZE);
        body.put("total", total == null ? 0 : total);
        body.put("items", items);
        return body;
    }
}
