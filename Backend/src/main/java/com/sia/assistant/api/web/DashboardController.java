package com.sia.assistant.api.web;

import com.sia.assistant.common.Times;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.ZonedDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * 운영 진단용 집계 (GET /api/dashboard/summary, /api/dashboard/timeseries). days 는 1~90 클램프.
 * ★ 와이어프레임에 대응 화면이 없다 — 사용자 대시보드는 DashboardCardsController(§1.15~§1.19)다.
 * 이쪽은 도구 게이트·오인식을 들여다보는 용도다.
 * byTool 의 기간 조건은 반드시 LEFT JOIN 의 ON 절에 둔다 — WHERE 로 옮기면
 * 기간 중 안 불린 도구가 결과에서 통째로 사라진다.
 *
 * <p><b>시각 축.</b> /summary 는 "지금부터 days 일 전"까지의 구르는 창이라 타임존과 무관하다.
 * /timeseries 는 날짜 칸을 만들므로 <b>로컬 날짜</b>다 — §1.15~§1.19 카드와 같은 축이다
 * (UTC 로 자르면 KST 기준 오전 9시에 날짜가 바뀌어 두 화면이 다른 하루를 보여 준다).
 */
@RestController
@RequestMapping("/api/dashboard")
public class DashboardController {

    private final JdbcTemplate jdbc;

    public DashboardController(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @GetMapping("/summary")
    public Map<String, Object> summary(@RequestParam(name = "days", defaultValue = "7") int days) {
        int d = clamp(days);
        String since = Times.daysAgo(d);

        List<Map<String, Object>> byOutcome = jdbc.query(
                "SELECT outcome, COUNT(*) AS cnt FROM tool_call WHERE ts >= ? GROUP BY outcome ORDER BY cnt DESC",
                (rs, i) -> mapOf("outcome", rs.getString("outcome"), "count", rs.getLong("cnt")), since);

        List<Map<String, Object>> byCaller = jdbc.query(
                "SELECT caller, COUNT(*) AS cnt FROM tool_call WHERE ts >= ? GROUP BY caller ORDER BY cnt DESC",
                (rs, i) -> mapOf("caller", rs.getString("caller"), "count", rs.getLong("cnt")), since);

        List<Map<String, Object>> byApp = jdbc.query(
                "SELECT a.app_key, a.display_name, COUNT(*) AS cnt FROM tool_call tc"
                        + " JOIN app_target a ON a.id = tc.app_target_id"
                        + " WHERE tc.ts >= ? GROUP BY a.id ORDER BY cnt DESC",
                (rs, i) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("appKey", rs.getString("app_key"));
                    row.put("displayName", rs.getString("display_name"));
                    row.put("count", rs.getLong("cnt"));
                    return row;
                }, since);

        // ★ 기간 조건은 ON 절 — 안 불린 도구도 calls=0 으로 남는다
        List<Map<String, Object>> byTool = jdbc.query(
                "SELECT t.name, COUNT(tc.id) AS calls,"
                        + " SUM(CASE WHEN tc.outcome = 'EXECUTED' THEN 1 ELSE 0 END) AS executed"
                        + " FROM tool t LEFT JOIN tool_call tc"
                        + "   ON tc.tool_name = t.name AND tc.ts >= ?"
                        + " GROUP BY t.name ORDER BY calls DESC, t.name",
                (rs, i) -> {
                    long calls = rs.getLong("calls");
                    long executed = rs.getLong("executed");
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("tool", rs.getString("name"));
                    row.put("calls", calls);
                    row.put("executed", executed);
                    row.put("successRate", calls == 0 ? null
                            : Math.round((double) executed / calls * 1000) / 1000.0);
                    return row;
                }, since);

        List<Map<String, Object>> avgLatencyByKind = jdbc.query(
                "SELECT kind, AVG(latency_ms) AS avg_ms, COUNT(latency_ms) AS cnt FROM usage_event"
                        + " WHERE received_at >= ? AND latency_ms IS NOT NULL GROUP BY kind ORDER BY kind",
                (rs, i) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("kind", rs.getString("kind"));
                    row.put("avgLatencyMs", Math.round(rs.getDouble("avg_ms") * 10) / 10.0);
                    row.put("count", rs.getLong("cnt"));
                    return row;
                }, since);

        List<Map<String, Object>> accuracyByKind = jdbc.query(
                "SELECT kind, AVG(accuracy) AS avg_acc, COUNT(accuracy) AS cnt FROM usage_event"
                        + " WHERE received_at >= ? AND accuracy IS NOT NULL GROUP BY kind ORDER BY kind",
                (rs, i) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("kind", rs.getString("kind"));
                    row.put("avgAccuracy", Math.round(rs.getDouble("avg_acc") * 1000) / 1000.0);
                    row.put("count", rs.getLong("cnt"));
                    return row;
                }, since);

        // 화자 게이트가 버린 발화 — 사용자 카드 넷에는 안 들어가고 여기서만 본다 (§2.3)
        Integer voiceRejected = jdbc.queryForObject(
                "SELECT COUNT(*) FROM usage_event WHERE received_at >= ? AND kind = 'voice-rejected'",
                Integer.class, since);

        Integer totalSessions = jdbc.queryForObject(
                "SELECT COUNT(*) FROM session WHERE started_at >= ?", Integer.class, since);
        Integer emptySessions = jdbc.queryForObject(
                "SELECT COUNT(*) FROM session s WHERE s.started_at >= ?"
                        + " AND NOT EXISTS (SELECT 1 FROM tool_call tc WHERE tc.session_id = s.id)",
                Integer.class, since);

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("days", d);
        body.put("byOutcome", byOutcome);
        body.put("byCaller", byCaller);
        body.put("byApp", byApp);
        body.put("byTool", byTool);
        body.put("avgLatencyByKind", avgLatencyByKind);
        body.put("accuracyByKind", accuracyByKind);
        body.put("voiceRejected", voiceRejected == null ? 0 : voiceRejected);
        body.put("emptySessions", emptySessions == null ? 0 : emptySessions);
        body.put("totalSessions", totalSessions == null ? 0 : totalSessions);
        return body;
    }

    @GetMapping("/timeseries")
    public Map<String, Object> timeseries(@RequestParam(name = "days", defaultValue = "7") int days) {
        int d = clamp(days);
        ZoneId zone = ZoneId.systemDefault();

        // 오늘 포함 d일. 데이터가 없는 날도 0 으로 채워 그래프 축이 끊기지 않게 한다.
        // 경계는 로컬 자정이다 — 옛 구현은 "지금부터 d일 전"이라 가장 오래된 칸이
        // 하루가 아니라 반나절만 세어 첫 막대가 늘 짧았다.
        LocalDate today = LocalDate.now(zone);
        List<DashboardBuckets.Bucket> buckets = new ArrayList<>(d);
        for (int i = d - 1; i >= 0; i--) {
            LocalDate date = today.minusDays(i);
            ZonedDateTime start = date.atStartOfDay(zone);
            String key = date.toString();
            buckets.add(new DashboardBuckets.Bucket(key, key, start, start.plusDays(1)));
        }
        String from = DashboardBuckets.utc(buckets.get(0).start());
        String to = DashboardBuckets.utc(buckets.get(buckets.size() - 1).end());

        long[][] counts = new long[buckets.size()][3];
        accumulate(counts, buckets, zone, 0,
                "SELECT substr(ts, 1, 13) AS h, COUNT(*) AS cnt FROM tool_call"
                        + " WHERE ts >= ? AND ts < ? GROUP BY h", from, to);
        accumulate(counts, buckets, zone, 1,
                "SELECT substr(started_at, 1, 13) AS h, COUNT(*) AS cnt FROM session"
                        + " WHERE started_at >= ? AND started_at < ? GROUP BY h", from, to);
        accumulate(counts, buckets, zone, 2,
                "SELECT substr(received_at, 1, 13) AS h, COUNT(*) AS cnt FROM usage_event"
                        + " WHERE received_at >= ? AND received_at < ? GROUP BY h", from, to);

        List<Map<String, Object>> items = new ArrayList<>();
        for (int i = 0; i < buckets.size(); i++) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("date", buckets.get(i).key());
            row.put("toolCalls", counts[i][0]);
            row.put("sessions", counts[i][1]);
            row.put("events", counts[i][2]);
            items.add(row);
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("days", d);
        body.put("items", items);
        return body;
    }

    /**
     * UTC 시각(substr 1~13)으로 모은 뒤 로컬 날짜 칸에 넣는다 — §1.15~§1.19 카드와 같은 방식이다.
     * 한 날짜 칸에 UTC 시각이 24개 들어오므로 대입이 아니라 <b>누적</b>이다.
     */
    private void accumulate(long[][] counts, List<DashboardBuckets.Bucket> buckets, ZoneId zone,
                            int slot, String sql, String from, String to) {
        jdbc.query(sql, rs -> {
            int idx = DashboardBuckets.indexOf(buckets, rs.getString("h"), zone);
            if (idx >= 0) {
                counts[idx][slot] += rs.getLong("cnt");
            }
        }, from, to);
    }

    private static int clamp(int days) {
        return Math.max(1, Math.min(90, days));
    }

    private static Map<String, Object> mapOf(String k1, Object v1, String k2, Object v2) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put(k1, v1);
        out.put(k2, v2);
        return out;
    }
}
