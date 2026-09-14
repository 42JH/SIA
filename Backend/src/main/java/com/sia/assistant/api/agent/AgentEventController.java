package com.sia.assistant.api.agent;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.JsonBody;
import com.sia.assistant.logging.UsageEventBatchWriter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * 통계 이벤트 배치 수신 (POST /api/agent/events).
 * 수용 규칙: 일부 실패도 200, 모르는 kind/payload 그대로 저장, eventUid 중복은 조용히 스킵,
 * sessionId 는 NULL 허용. rejected = eventUid 나 kind 가 없는 항목.
 * 본문은 이벤트 배열이거나 {"events":[...]} 봉투 둘 다 받는다.
 */
@RestController
public class AgentEventController {

    private static final Logger log = LoggerFactory.getLogger(AgentEventController.class);

    private final UsageEventBatchWriter writer;
    private final ObjectMapper om;

    public AgentEventController(UsageEventBatchWriter writer, ObjectMapper om) {
        this.writer = writer;
        this.om = om;
    }

    @PostMapping("/api/agent/events")
    public Map<String, Object> post(@RequestBody String rawBody) {
        JsonNode body = JsonBody.parse(om, rawBody);
        JsonNode array = body != null && body.isArray() ? body : body == null ? null : body.path("events");
        if (array == null || !array.isArray()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "이벤트 배열이 필요합니다 (본문 자체가 배열이거나 events 필드)");
        }
        List<Map<String, Object>> events = new ArrayList<>();
        for (JsonNode node : array) {
            try {
                events.add(om.convertValue(node, new TypeReference<Map<String, Object>>() {
                }));
            } catch (Exception e) {
                log.warn("이벤트 항목 변환 실패 — rejected 로 셉니다: {}", node);
                events.add(Map.of()); // eventUid/kind 가 없으므로 writer 가 rejected 로 센다
            }
        }
        UsageEventBatchWriter.Result result = writer.write(events);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("accepted", result.accepted());
        out.put("duplicates", result.duplicates());
        out.put("rejected", result.rejected());
        return out;
    }
}
