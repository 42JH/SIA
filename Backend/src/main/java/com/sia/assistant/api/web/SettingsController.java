package com.sia.assistant.api.web;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.JsonBody;
import com.sia.assistant.settings.SettingsService;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * 설정 조회·교체 (FE 전용).
 * PUT 본문: {"settings": {...}, "updatedAt": "yyyy-MM-dd HH:mm:ss.SSS"} — updatedAt 은
 * FE 가 마지막으로 불러온 설정의 시각이다. 저장분보다 과거면 SETTINGS_STALE(409).
 */
@RestController
@RequestMapping("/api/settings")
public class SettingsController {

    private final ObjectMapper om;

    private final SettingsService settingsService;

    public SettingsController(SettingsService settingsService, ObjectMapper om) {
        this.om = om;
        this.settingsService = settingsService;
    }

    @GetMapping
    public Map<String, Object> get() {
        return settingsService.get();
    }

    @PutMapping
    public Map<String, Object> put(@RequestBody String rawBody) {
        JsonNode body = JsonBody.parse(om, rawBody);
        if (body == null || !body.isObject()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "설정 본문은 JSON 객체여야 합니다");
        }
        JsonNode settings = body.has("settings") ? body.get("settings") : body;
        String updatedAt = body.hasNonNull("updatedAt") ? body.get("updatedAt").asText()
                : settings.hasNonNull("updatedAt") ? settings.get("updatedAt").asText() : null;
        settingsService.replace(settings, updatedAt);
        return settingsService.get();
    }
}
