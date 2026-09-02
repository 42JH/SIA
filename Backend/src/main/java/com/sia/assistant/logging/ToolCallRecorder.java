package com.sia.assistant.logging;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sia.assistant.common.JsonTruncate;
import com.sia.assistant.common.Times;
import com.sia.assistant.mcp.Caller;
import com.sia.assistant.ws.FeHub;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

/**
 * tool_call 기록의 유일한 통로. 명령 트랜잭션과 분리(REQUIRES_NEW)되어
 * 명령이 굴러도 기록은 남고, 기록이 실패해도 명령은 죽지 않는다(log.error 만).
 * 기록 후 FE 에 tool_result 를 push 한다.
 */
@Service
public class ToolCallRecorder {

    private static final Logger log = LoggerFactory.getLogger(ToolCallRecorder.class);
    private static final int ARGS_MAX = 500;
    private static final int REASON_MAX = 255;

    /** app.launch 가 실행 직전에 심는 app_target id — 같은 스레드의 다음 record 가 소비한다. */
    private static final ThreadLocal<Long> APP_TARGET_HINT = new ThreadLocal<>();

    private final JdbcTemplate jdbc;
    private final ObjectMapper om;
    private final FeHub feHub;

    public ToolCallRecorder(JdbcTemplate jdbc, ObjectMapper om, FeHub feHub) {
        this.jdbc = jdbc;
        this.om = om;
        this.feHub = feHub;
    }

    @Transactional(propagation = Propagation.REQUIRES_NEW)
    public void record(String tool, Map<String, Object> args, Caller caller, String outcome,
                       String reason, Long sessionId, long latencyMs) {
        String callerName = (caller == null ? Caller.LLM : caller).name();
        String reasonCut = truncate(reason, REASON_MAX);
        try {
            Long appTargetId = APP_TARGET_HINT.get();
            // args_json 은 JSON 컬럼 — 넘치면 substring 이 아니라 유효한 JSON 으로 감싼다
            String argsJson = JsonTruncate.toFit(om, serialize(args), ARGS_MAX);
            jdbc.update("INSERT INTO tool_call (session_id, app_target_id, tool_name, ts, args_json,"
                            + " caller, outcome, reason, latency_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    sessionId, appTargetId, tool, Times.now(), argsJson,
                    callerName, outcome, reasonCut, latencyMs);
        } catch (Exception e) {
            log.error("tool_call 기록 실패: tool={}, outcome={}", tool, outcome, e);
        } finally {
            APP_TARGET_HINT.remove();
        }

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("tool", tool);
        body.put("outcome", outcome);
        body.put("caller", callerName);
        if (reasonCut != null) {
            body.put("message", reasonCut);
        }
        body.put("latencyMs", latencyMs);
        feHub.send("tool_result", body);
    }

    /** app.launch 전용 — 실행 직전에 대상 app_target id 를 심어 두면 record 가 집계 컬럼에 싣는다. */
    public void hintAppTarget(Long id) {
        if (id == null) {
            APP_TARGET_HINT.remove();
        } else {
            APP_TARGET_HINT.set(id);
        }
    }

    private String serialize(Map<String, Object> args) {
        if (args == null || args.isEmpty()) {
            return "{}";
        }
        try {
            return om.writeValueAsString(args);
        } catch (Exception e) {
            return "{}";
        }
    }

    /** reason 은 사람이 읽는 평문이라 그냥 자른다 — JSON 은 {@link JsonTruncate} 를 쓴다. */
    private static String truncate(String value, int max) {
        if (value == null) {
            return null;
        }
        return value.length() <= max ? value : value.substring(0, max);
    }
}
