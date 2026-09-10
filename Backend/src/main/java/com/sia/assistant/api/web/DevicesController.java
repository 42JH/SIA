package com.sia.assistant.api.web;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.JsonBody;
import com.sia.assistant.profile.CalibProfileService;
import com.sia.assistant.profile.VoiceProfileService;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/**
 * 장비 교체 후 프로필 자동 맵핑 (회의 확정 2026-09-01).
 * 설정에서 마이크/카메라를 바꾼 뒤 FE 가 부른다:
 *  - 그 장비로 만든 프로필이 1개 → 자동으로 사용으로 설정하고 activated 에 담아 준다.
 *  - 2개 이상 → 자동 전환하지 않는다. 최근 사용일 내림차순 목록을 돌려줘 사용자가 고른다
 *    (고른 뒤 FE 가 POST /api/{voices|calibs}/{id}/activate).
 *  - 0개 → 빈 목록 — FE 가 재등록(03/07 화면)으로 유도한다.
 */
@RestController
public class DevicesController {

    private final VoiceProfileService voiceProfiles;
    private final CalibProfileService calibProfiles;
    private final ObjectMapper om;

    public DevicesController(VoiceProfileService voiceProfiles, CalibProfileService calibProfiles,
                             ObjectMapper om) {
        this.voiceProfiles = voiceProfiles;
        this.calibProfiles = calibProfiles;
        this.om = om;
    }

    /** 본문 {kind: "mic"|"camera", deviceLabel} → {kind, deviceLabel, activated: {...}|null, matches: [...]} */
    @PostMapping("/api/devices/remap")
    public Map<String, Object> remap(@RequestBody String raw) {
        JsonNode body = JsonBody.parseObject(om, raw);
        String kind = body.path("kind").asText("");
        String deviceLabel = body.path("deviceLabel").asText("");
        if (deviceLabel.isBlank()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "deviceLabel 이 필요합니다");
        }

        List<Map<String, Object>> matches = switch (kind) {
            case "mic" -> voiceProfiles.byDevice(deviceLabel);
            case "camera" -> calibProfiles.byDevice(deviceLabel);
            default -> throw new ApiException(ErrorCode.INVALID_REQUEST, "kind 는 mic 또는 camera 여야 합니다");
        };

        Map<String, Object> activated = null;
        if (matches.size() == 1) {
            long id = ((Number) matches.get(0).get("id")).longValue();
            activated = "mic".equals(kind) ? voiceProfiles.activate(id) : calibProfiles.activate(id);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("kind", kind);
        out.put("deviceLabel", deviceLabel);
        out.put("activated", activated);
        out.put("matches", matches);
        return out;
    }
}
