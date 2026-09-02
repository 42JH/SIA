package com.sia.assistant.api.web;

import com.sia.assistant.api.web.DashboardBuckets.Bucket;
import com.sia.assistant.api.web.DashboardBuckets.Spec;
import com.sia.assistant.common.Times;
import java.time.ZoneId;
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
 * 와이어프레임 대시보드의 카드 4종 + 첫 화면 묶음 (API.md §1.15 ~ §1.19).
 * 운영 진단용 summary·timeseries 는 {@link DashboardController} 에 그대로 남아 있다.
 *
 * <p>공통 규칙 셋 (§1.14):
 * <ul>
 *   <li><b>빈 버킷도 채운다.</b> 개수는 0, 평균은 <b>null</b> — 표본 없는 구간을 0 으로 그리면
 *       "정확도 0%" 라는 거짓말이 된다.</li>
 *   <li><b>summary 는 버킷 재평균이 아니다.</b> 합과 개수를 기간 전체로 다시 나눈다 —
 *       표본 수가 다른 버킷을 같은 무게로 세면 틀린다.</li>
 *   <li>모르는 period 는 조용히 클램프하지 않고 400 이다.</li>
 * </ul>
 *
 * <p>집계는 <b>UTC 시간 단위로 GROUP BY 한 뒤 Java 에서 로컬 버킷에 넣는다</b>.
 * 1년치라도 최대 8,760행이라 싸고, 로컬 경계를 UTC SQL 표현식으로 옮기는 위험을 피한다.
 */
@RestController
@RequestMapping("/api/dashboard")
public class DashboardCardsController {

    /** 인식 정확도 세 계열. UI 의 "모션인식" 이 kind='gesture' 다. */
    private static final String ACCURACY_KINDS = "('voice', 'gaze', 'gesture')";

    private final JdbcTemplate jdbc;
    private final ZoneId zone = ZoneId.systemDefault();

    public DashboardCardsController(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    // ------------------------------------------------------------------ §1.15
    /** 첫 화면 카드 4개를 한 번에. 카드마다 와이어프레임이 정한 기간이 달라 인자가 없다. */
    @GetMapping("/overview")
    public Map<String, Object> overview() {
        Map<String, Object> accuracy = accuracy("week");
        Map<String, Object> latency = latency("week");
        Map<String, Object> usage = usage("week");
        Map<String, Object> apps = apps("day", 5);

        Map<String, Object> accSum = cast(accuracy.get("summary"));
        Map<String, Object> accBlock = new LinkedHashMap<>();
        accBlock.put("period", "week");
        accBlock.put("voice", accSum.get("voice"));
        accBlock.put("gaze", accSum.get("gaze"));
        accBlock.put("motion", accSum.get("motion"));
        accBlock.put("sampleCount", accSum.get("sampleCount"));

        Map<String, Object> latSum = cast(latency.get("summary"));
        Map<String, Object> latBlock = new LinkedHashMap<>();
        latBlock.put("period", "week");
        latBlock.put("simpleMs", latSum.get("simpleMs"));
        latBlock.put("complexMs", latSum.get("complexMs"));
        latBlock.put("simpleCount", latSum.get("simpleCount"));
        latBlock.put("complexCount", latSum.get("complexCount"));

        // 첫 화면 막대는 합산만 그린다 — 내역(gesture/voice)은 상세(§1.18)에서 본다
        List<Map<String, Object>> slim = new ArrayList<>();
        for (Map<String, Object> b : this.<Map<String, Object>>castList(usage.get("buckets"))) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("key", b.get("key"));
            row.put("label", b.get("label"));
            row.put("count", b.get("count"));
            slim.add(row);
        }
        Map<String, Object> usageBlock = new LinkedHashMap<>();
        usageBlock.put("period", "week");
        usageBlock.put("bucketUnit", usage.get("bucketUnit"));
        usageBlock.put("buckets", slim);
        usageBlock.put("total", cast(usage.get("summary")).get("total"));

        List<Map<String, Object>> topApps = new ArrayList<>();
        for (Map<String, Object> a : this.<Map<String, Object>>castList(apps.get("items"))) {
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("appKey", a.get("appKey"));
            row.put("displayName", a.get("displayName"));
            row.put("count", a.get("count"));
            topApps.add(row);
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("generatedAt", Times.now());
        body.put("accuracy", accBlock);
        body.put("latency", latBlock);
        body.put("usage", usageBlock);
        body.put("topApps", topApps);
        return body;
    }

    // ------------------------------------------------------------------ §1.16
    @GetMapping("/accuracy")
    public Map<String, Object> accuracy(@RequestParam(name = "period", defaultValue = "day") String period) {
        Spec spec = DashboardBuckets.of(period, zone);
        int n = spec.buckets().size();
        // [0]=voice [1]=gaze [2]=gesture(모션)
        long[][] cnt = new long[n][3];
        double[][] sum = new double[n][3];

        jdbc.query("SELECT substr(received_at, 1, 13) AS h, kind,"
                + " COUNT(accuracy) AS c, SUM(accuracy) AS s"
                + " FROM usage_event"
                + " WHERE received_at >= ? AND received_at < ?"
                + "   AND accuracy IS NOT NULL AND kind IN " + ACCURACY_KINDS
                + " GROUP BY h, kind", rs -> {
            int i = DashboardBuckets.indexOf(spec.buckets(), rs.getString("h"), zone);
            int s = seriesOf(rs.getString("kind"));
            if (i >= 0 && s >= 0) {
                cnt[i][s] += rs.getLong("c");
                sum[i][s] += rs.getDouble("s");
            }
        }, DashboardBuckets.utc(spec.from()), DashboardBuckets.utc(spec.to()));

        List<Map<String, Object>> buckets = new ArrayList<>(n);
        long[] totalCnt = new long[3];
        double[] totalSum = new double[3];
        for (int i = 0; i < n; i++) {
            Bucket b = spec.buckets().get(i);
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("key", b.key());
            row.put("label", b.label());
            row.put("voice", ratio(sum[i][0], cnt[i][0]));
            row.put("gaze", ratio(sum[i][1], cnt[i][1]));
            row.put("motion", ratio(sum[i][2], cnt[i][2]));
            row.put("sampleCount", cnt[i][0] + cnt[i][1] + cnt[i][2]);
            buckets.add(row);
            for (int s = 0; s < 3; s++) {
                totalCnt[s] += cnt[i][s];
                totalSum[s] += sum[i][s];
            }
        }

        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("voice", ratio(totalSum[0], totalCnt[0]));
        summary.put("gaze", ratio(totalSum[1], totalCnt[1]));
        summary.put("motion", ratio(totalSum[2], totalCnt[2]));
        summary.put("sampleCount", totalCnt[0] + totalCnt[1] + totalCnt[2]);
        return card(spec, buckets, summary);
    }

    // ------------------------------------------------------------------ §1.17
    /**
     * 사용자가 <b>체감하는</b> 시간이다 — tool_call.latency_ms(BE 실행 시간)가 아니라
     * kind='command' 이벤트의 latency_ms(호출어~결과 전 구간)를 읽는다.
     * complexity 가 없는 이벤트는 통째로 제외한다 — SIMPLE 로 넘겨짚지 않는다.
     */
    @GetMapping("/latency")
    public Map<String, Object> latency(@RequestParam(name = "period", defaultValue = "day") String period) {
        Spec spec = DashboardBuckets.of(period, zone);
        int n = spec.buckets().size();
        long[][] cnt = new long[n][2];   // [0]=SIMPLE [1]=COMPLEX
        double[][] sum = new double[n][2];

        jdbc.query("SELECT substr(received_at, 1, 13) AS h, complexity,"
                + " COUNT(latency_ms) AS c, SUM(latency_ms) AS s"
                + " FROM usage_event"
                + " WHERE received_at >= ? AND received_at < ?"
                + "   AND kind = 'command' AND latency_ms IS NOT NULL AND complexity IS NOT NULL"
                + " GROUP BY h, complexity", rs -> {
            int i = DashboardBuckets.indexOf(spec.buckets(), rs.getString("h"), zone);
            int s = "SIMPLE".equals(rs.getString("complexity")) ? 0 : 1;
            if (i >= 0) {
                cnt[i][s] += rs.getLong("c");
                sum[i][s] += rs.getDouble("s");
            }
        }, DashboardBuckets.utc(spec.from()), DashboardBuckets.utc(spec.to()));

        List<Map<String, Object>> buckets = new ArrayList<>(n);
        long[] totalCnt = new long[2];
        double[] totalSum = new double[2];
        for (int i = 0; i < n; i++) {
            Bucket b = spec.buckets().get(i);
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("key", b.key());
            row.put("label", b.label());
            row.put("simpleMs", millis(sum[i][0], cnt[i][0]));
            row.put("complexMs", millis(sum[i][1], cnt[i][1]));
            row.put("simpleCount", cnt[i][0]);
            row.put("complexCount", cnt[i][1]);
            buckets.add(row);
            for (int s = 0; s < 2; s++) {
                totalCnt[s] += cnt[i][s];
                totalSum[s] += sum[i][s];
            }
        }

        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("simpleMs", millis(totalSum[0], totalCnt[0]));
        summary.put("complexMs", millis(totalSum[1], totalCnt[1]));
        // ★ 표본 가중 평균이다. (simpleMs + complexMs) / 2 가 아니다
        summary.put("overallMs", millis(totalSum[0] + totalSum[1], totalCnt[0] + totalCnt[1]));
        summary.put("simpleCount", totalCnt[0]);
        summary.put("complexCount", totalCnt[1]);
        return card(spec, buckets, summary);
    }

    // ------------------------------------------------------------------ §1.18
    /** 제스처 + 보이스 합산 사용량. voice-rejected 는 세지 않는다 — 폐기된 발화는 "사용"이 아니다. */
    @GetMapping("/usage")
    public Map<String, Object> usage(@RequestParam(name = "period", defaultValue = "day") String period) {
        Spec spec = DashboardBuckets.of(period, zone);
        int n = spec.buckets().size();
        long[][] cnt = new long[n][2];   // [0]=gesture [1]=voice

        jdbc.query("SELECT substr(received_at, 1, 13) AS h, kind, COUNT(*) AS c"
                + " FROM usage_event"
                + " WHERE received_at >= ? AND received_at < ? AND kind IN ('gesture', 'voice')"
                + " GROUP BY h, kind", rs -> {
            int i = DashboardBuckets.indexOf(spec.buckets(), rs.getString("h"), zone);
            if (i >= 0) {
                cnt[i]["gesture".equals(rs.getString("kind")) ? 0 : 1] += rs.getLong("c");
            }
        }, DashboardBuckets.utc(spec.from()), DashboardBuckets.utc(spec.to()));

        List<Map<String, Object>> buckets = new ArrayList<>(n);
        long total = 0;
        int peakIdx = -1;
        long peakCount = 0;
        for (int i = 0; i < n; i++) {
            Bucket b = spec.buckets().get(i);
            long c = cnt[i][0] + cnt[i][1];
            Map<String, Object> row = new LinkedHashMap<>();
            row.put("key", b.key());
            row.put("label", b.label());
            row.put("count", c);
            row.put("gesture", cnt[i][0]);
            row.put("voice", cnt[i][1]);
            buckets.add(row);
            total += c;
            if (c > peakCount) {   // 동률이면 먼저 오는 버킷을 남긴다
                peakCount = c;
                peakIdx = i;
            }
        }

        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("total", total);
        // ★ 분모는 버킷 수가 아니다 — day 는 버킷 8개지만 "시간당 평균"이라 24 로 나눈다
        summary.put("average", Math.round((double) total / spec.averageDivisor() * 10) / 10.0);
        summary.put("averageUnit", spec.averageUnit());
        if (peakIdx < 0 || peakCount == 0) {
            summary.put("peak", null);
        } else {
            Map<String, Object> peak = new LinkedHashMap<>();
            peak.put("key", spec.buckets().get(peakIdx).key());
            peak.put("label", spec.buckets().get(peakIdx).label());
            peak.put("count", peakCount);
            summary.put("peak", peak);
        }
        return card(spec, buckets, summary);
    }

    // ------------------------------------------------------------------ §1.19
    /**
     * 실행된 app.launch 만 센다 — 차단·실패한 실행은 "사용"이 아니다.
     * 축이 app_target 이라 등록되지 않은 경로로 뜬 창은 잡히지 않는다(문서에 적힌 한계).
     */
    @GetMapping("/apps")
    public Map<String, Object> apps(@RequestParam(name = "period", defaultValue = "day") String period,
                                    @RequestParam(name = "limit", defaultValue = "10") int limit) {
        Spec spec = DashboardBuckets.of(period, zone);
        int cap = Math.max(1, Math.min(20, limit));

        List<Map<String, Object>> all = jdbc.query(
                "SELECT a.app_key AS k, a.display_name AS n, COUNT(*) AS c"
                        + " FROM tool_call tc JOIN app_target a ON a.id = tc.app_target_id"
                        + " WHERE tc.ts >= ? AND tc.ts < ?"
                        + "   AND tc.tool_name = 'app.launch' AND tc.outcome = 'EXECUTED'"
                        + " GROUP BY a.id ORDER BY c DESC, a.app_key",
                (rs, i) -> {
                    Map<String, Object> row = new LinkedHashMap<>();
                    row.put("appKey", rs.getString("k"));
                    // 등록이 해제됐으면 app_key 를 그대로 쓴다
                    String name = rs.getString("n");
                    row.put("displayName", name == null || name.isBlank() ? rs.getString("k") : name);
                    row.put("count", rs.getLong("c"));
                    return row;
                }, DashboardBuckets.utc(spec.from()), DashboardBuckets.utc(spec.to()));

        // ★ limit 에 잘리기 전 전체 합이다 — 그래서 share 의 합이 1 이 안 될 수 있다
        long total = all.stream().mapToLong(r -> (Long) r.get("count")).sum();
        List<Map<String, Object>> items = new ArrayList<>(Math.min(cap, all.size()));
        for (int i = 0; i < all.size() && i < cap; i++) {
            Map<String, Object> row = all.get(i);
            long c = (Long) row.get("count");
            row.put("share", total == 0 ? 0.0 : Math.round((double) c / total * 1000) / 1000.0);
            items.add(row);
        }

        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("totalLaunches", total);
        summary.put("topAppKey", all.isEmpty() ? null : all.get(0).get("appKey"));
        summary.put("topDisplayName", all.isEmpty() ? null : all.get(0).get("displayName"));
        summary.put("topCount", all.isEmpty() ? 0L : all.get(0).get("count"));

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("period", spec.period());
        body.put("items", items);
        body.put("summary", summary);
        return body;
    }

    // ------------------------------------------------------------------ 공통
    private static Map<String, Object> card(Spec spec, List<Map<String, Object>> buckets,
                                            Map<String, Object> summary) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("period", spec.period());
        body.put("bucketUnit", spec.bucketUnit());
        body.put("buckets", buckets);
        body.put("summary", summary);
        return body;
    }

    private static int seriesOf(String kind) {
        return switch (kind == null ? "" : kind) {
            case "voice" -> 0;
            case "gaze" -> 1;
            case "gesture" -> 2;
            default -> -1;
        };
    }

    /** 표본이 없으면 0 이 아니라 <b>null</b> 이다 — 0% 는 거짓말이다. */
    private static Double ratio(double sum, long count) {
        return count == 0 ? null : Math.round(sum / count * 1000) / 1000.0;
    }

    private static Long millis(double sum, long count) {
        return count == 0 ? null : Math.round(sum / count);
    }

    @SuppressWarnings("unchecked")
    private static Map<String, Object> cast(Object o) {
        return (Map<String, Object>) o;
    }

    @SuppressWarnings("unchecked")
    private <T> List<T> castList(Object o) {
        return (List<T>) o;
    }
}
