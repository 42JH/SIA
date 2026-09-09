package com.sia.assistant.logging;

import com.sia.assistant.common.JsonTruncate;
import com.sia.assistant.common.Times;
import java.util.List;
import java.util.Map;
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

    private final JdbcTemplate jdbc;
    private final ObjectMapper om;

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
                // payload 는 "모르는 키를 버리지 않는다"가 목적이라 잘려도 JSON 이어야 한다
                String payload = JsonTruncate.toFit(om, serializePayload(event.get("payload")), PAYLOAD_MAX);
                int inserted = jdbc.update("INSERT OR IGNORE INTO usage_event"
                                + " (event_uid, session_id, profile_id, received_at, kind, action, context,"
                                + "  latency_ms, accuracy, complexity, payload)"
                                + " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        eventUid, sessionId, longOrNull(event.get("profileId")), receivedAt, kind,
                        str(event.get("action")), str(event.get("context")),
                        intOrNull(event.get("latencyMs")),
                        accuracyOrNull(event.get("accuracy")),
                        complexityOrNull(event.get("complexity")),
                        payload);
                if (inserted == 0) {
                    duplicates++;
                } else {
                    accepted++;
                }
            } catch (Exception e) {
                log.warn("usage_event 기록 실패 — 항목을 건너뜁니다: {}", event, e);
                rejected++;
            }
        }
        return new Result(accepted, duplicates, rejected);
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
