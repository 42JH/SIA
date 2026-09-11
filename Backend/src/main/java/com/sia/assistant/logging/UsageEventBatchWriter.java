package com.sia.assistant.logging;

import com.sia.assistant.common.JsonTruncate;
import com.sia.assistant.common.Times;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.ObjectMapper;

/**
 * usage_event 배치 기록. event_uid UNIQUE + INSERT OR IGNORE 로 재전송이 멱등이다.
 * 미지의 session_id 는 NULL 로 낮추고, 모르는 kind 도 그대로 저장한다 — 통계는 관대하게 받는다.
 */
@Service
public class UsageEventBatchWriter {

    public record Result(int accepted, int duplicates, int rejected) {
    }

    private static final Logger log = LoggerFactory.getLogger(UsageEventBatchWriter.class);
    private static final int PAYLOAD_MAX = 1000;

    /**
     * 대시보드가 축으로 쓰는 kind 와, 그 카드가 실제로 읽는 컬럼 (API명세서 §2.3).
     * 저장 규칙은 이 표와 무관하다 — 경고 판단에만 쓴다.
     */
    private static final Map<String, List<String>> DASHBOARD_METRICS = Map.of(
            "voice", List.of("accuracy", "profileId"),
            "stt", List.of("accuracy", "profileId"), // voice 의 별칭
            "gaze", List.of("accuracy", "profileId"),
            "gesture", List.of("accuracy"),
            "command", List.of("latencyMs", "complexity"));

    /** 대시보드가 아는 kind 전부. 그 밖의 kind 도 저장하되 어휘가 어긋났다고 한 번 알린다. */
    private static final Set<String> KNOWN_KINDS = Set.of(
            "voice", "stt", "gaze", "gesture", "command", "voice-rejected", "calibration");

    private final JdbcTemplate jdbc;
    private final ObjectMapper om;

    /**
     * 이미 경고한 (kind, 사유) 조합. 계약 불일치는 배치마다 알릴 이벤트가 아니라 지속 상태라
     * 한 번만 남긴다 — 5초 배치가 계속 들어오는데 매번 찍으면 통신 로그가 묻힌다.
     */
    private final Set<String> warned = ConcurrentHashMap.newKeySet();

    public UsageEventBatchWriter(JdbcTemplate jdbc, ObjectMapper om) {
        this.jdbc = jdbc;
        this.om = om;
    }

    /**
     * 이벤트 맵 키: eventUid(필수), kind(필수), sessionId?, profileId?, action?, context?, latencyMs?,
     * accuracy?, complexity?, payload?. accuracy·complexity·profileId 는 payload 가 아니라 컬럼으로 받는다 —
     * 대시보드가 GROUP BY·AVG 하는 값이기 때문이다.
     * profileId 는 kind=voice 면 voice_profile.id, kind=gaze 면 calib_profile.id — 프로필별 정확도의 축이다.
     * received_at 은 서버 시각. eventUid/kind 가 없는 항목만 rejected 로 센다.
     */
    public Result write(List<Map<String, Object>> events) {
        if (events == null || events.isEmpty()) {
            return new Result(0, 0, 0);
        }
        int accepted = 0;
        int duplicates = 0;
        int rejected = 0;
        String receivedAt = Times.now();
        Map<String, Integer> storedByKind = new HashMap<>();
        Map<String, Map<String, Integer>> missingByKind = new HashMap<>();
        for (Map<String, Object> event : events) {
            try {
                String eventUid = str(event.get("eventUid"));
                String kind = str(event.get("kind"));
                if (eventUid == null || eventUid.isBlank() || kind == null || kind.isBlank()) {
                    rejected++;
                    continue;
                }
                Long sessionId = longOrNull(event.get("sessionId"));
                if (sessionId != null && !sessionExists(sessionId)) {
                    sessionId = null; // 모르는 세션은 통째로 버리지 않고 세션 없는 이벤트로 낮춘다
                }
                Long profileId = longOrNull(event.get("profileId"));
                Integer latencyMs = intOrNull(event.get("latencyMs"));
                Double accuracy = accuracyOrNull(event.get("accuracy"));
                String complexity = complexityOrNull(event.get("complexity"));
                // payload 는 "모르는 키를 버리지 않는다"가 목적이라 잘려도 JSON 이어야 한다
                String payload = JsonTruncate.toFit(om, serializePayload(event.get("payload")), PAYLOAD_MAX);
                int inserted = jdbc.update("INSERT OR IGNORE INTO usage_event"
                                + " (event_uid, session_id, profile_id, received_at, kind, action, context,"
                                + "  latency_ms, accuracy, complexity, payload)"
                                + " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        eventUid, sessionId, profileId, receivedAt, kind,
                        str(event.get("action")), str(event.get("context")),
                        latencyMs, accuracy, complexity, payload);
                if (inserted == 0) {
                    duplicates++;
                } else {
                    accepted++;
                    noteMetricGaps(storedByKind, missingByKind, kind,
                            profileId, latencyMs, accuracy, complexity);
                }
            } catch (Exception e) {
                log.warn("usage_event 기록 실패 — 항목을 건너뜁니다: {}", event, e);
                rejected++;
            }
        }
        warnContractGaps(storedByKind, missingByKind);
        return new Result(accepted, duplicates, rejected);
    }

    /** kind 별로 저장 건수와 "대시보드가 읽는 컬럼이 빈" 건수를 센다. */
    private static void noteMetricGaps(Map<String, Integer> storedByKind,
                                       Map<String, Map<String, Integer>> missingByKind, String kind,
                                       Long profileId, Integer latencyMs, Double accuracy,
                                       String complexity) {
        storedByKind.merge(kind, 1, Integer::sum);
        List<String> metrics = DASHBOARD_METRICS.get(kind);
        if (metrics == null) {
            return;
        }
        Map<String, Integer> byMetric = missingByKind.computeIfAbsent(kind, k -> new HashMap<>());
        for (String metric : metrics) {
            Object value = switch (metric) {
                case "accuracy" -> accuracy;
                case "profileId" -> profileId;
                case "latencyMs" -> latencyMs;
                case "complexity" -> complexity;
                default -> null;
            };
            if (value == null) {
                byMetric.merge(metric, 1, Integer::sum);
            }
        }
    }

    /**
     * 배치가 끝난 뒤 계약 불일치만 알린다. 저장도 응답도 바뀌지 않는다 —
     * {@code accepted} 카운터로는 드러나지 않는 것을 로그로 남기는 게 전부다.
     * <p>지표가 <b>일부만</b> 비는 건 정상이라 넘어간다: 동적 제스처는 신뢰도가 없고, 보이스·보정
     * 프로필이 없으면 profileId 도 없다. 전건 누락일 때만 어휘·매핑이 어긋난 것으로 본다.
     */
    private void warnContractGaps(Map<String, Integer> storedByKind,
                                  Map<String, Map<String, Integer>> missingByKind) {
        storedByKind.forEach((kind, count) -> {
            if (!KNOWN_KINDS.contains(kind) && warned.add("unknown:" + kind)) {
                log.warn("usage_event kind={} {}건 — 대시보드가 모르는 kind 입니다."
                        + " 저장은 했지만 어느 카드에도 잡히지 않습니다 (API명세서 §2.3)", kind, count);
            }
        });
        missingByKind.forEach((kind, byMetric) -> {
            int count = storedByKind.getOrDefault(kind, 0);
            List<String> allMissing = new ArrayList<>();
            for (String metric : DASHBOARD_METRICS.getOrDefault(kind, List.of())) {
                if (byMetric.getOrDefault(metric, 0) == count) {
                    allMissing.add(metric); // 그 kind 전건에서 비었을 때만
                }
            }
            if (!allMissing.isEmpty() && warned.add("missing:" + kind + ":" + allMissing)) {
                log.warn("usage_event kind={} {}건이 전부 {} 없이 왔습니다 —"
                        + " 해당 대시보드 카드에서 빠집니다 (API명세서 §2.3)", kind, count, allMissing);
            }
        });
    }

    private boolean sessionExists(long sessionId) {
        Integer count = jdbc.queryForObject("SELECT COUNT(*) FROM session WHERE id = ?",
                Integer.class, sessionId);
        return count != null && count > 0;
    }

    private String serializePayload(Object payload) {
        if (payload == null) {
            return "{}";
        }
        if (payload instanceof String s) {
            return s;
        }
        try {
            return om.writeValueAsString(payload);
        } catch (Exception e) {
            return "{}";
        }
    }

    private static String str(Object value) {
        return value == null ? null : String.valueOf(value);
    }

    private static Long longOrNull(Object value) {
        if (value == null) {
            return null;
        }
        if (value instanceof Number n) {
            return n.longValue();
        }
        try {
            return Long.parseLong(String.valueOf(value));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    /**
     * 0.0 ~ 1.0 만 받는다. 범위 밖·숫자 아님은 <b>그 필드만</b> null 로 낮춘다 —
     * 이벤트 자체는 버리지 않는다(통계는 관대하게 받는다).
     */
    private static Double accuracyOrNull(Object value) {
        if (value == null) {
            return null;
        }
        double v;
        if (value instanceof Number n) {
            v = n.doubleValue();
        } else {
            try {
                v = Double.parseDouble(String.valueOf(value));
            } catch (NumberFormatException e) {
                return null;
            }
        }
        return (v < 0.0 || v > 1.0 || Double.isNaN(v)) ? null : v;
    }

    /**
     * SIMPLE | COMPLEX 만 받는다. 그 밖의 값은 null 로 낮춘다 —
     * ★ SIMPLE 로 넘겨짚지 않는다. 없으면 평균 응답 시간 카드에서 통째로 빠지는 게 맞다.
     */
    private static String complexityOrNull(Object value) {
        if (value == null) {
            return null;
        }
        String v = String.valueOf(value).trim().toUpperCase(java.util.Locale.ROOT);
        return ("SIMPLE".equals(v) || "COMPLEX".equals(v)) ? v : null;
    }

    private static Integer intOrNull(Object value) {
        Long v = longOrNull(value);
        return v == null ? null : v.intValue();
    }
}
