package com.sia.assistant.common;

import java.util.LinkedHashMap;
import java.util.Map;
import tools.jackson.databind.ObjectMapper;

/**
 * JSON 문자열을 컬럼 길이에 맞춘다.
 *
 * <p><b>왜 substring 이 아닌가.</b> {@code tool_call.args_json}(500) 과
 * {@code usage_event.payload}(1000) 는 JSON 컬럼이고, 중간에서 자른 JSON 은 파싱되지 않는다.
 * {@code GET /api/tool-calls} 는 {@code args_json} 을 문자열 그대로 내보내므로
 * 잘린 행 하나가 소비자의 파싱을 깨뜨리고, {@code payload} 는 "모르는 키를 버리지 않는다"는
 * 목적 자체가 절단으로 훼손된다.
 *
 * <p>그래서 넘치면 <b>유효한 JSON 객체</b>로 바꾼다 —
 * {@code {"_truncated":<원본 길이>,"_preview":"<앞부분>"}}.
 * 파싱은 항상 성공하고, {@code _truncated} 키 하나로 잘린 행임이 드러난다.
 */
public final class JsonTruncate {

    /** 이스케이프로 늘어난 길이를 되돌리는 반복 횟수 상한 — 보통 1~2회면 맞는다. */
    private static final int MAX_ATTEMPTS = 8;

    private JsonTruncate() {
    }

    /** {@code max} 이하의 유효한 JSON 을 준다. null 과 이미 짧은 값은 그대로 통과한다. */
    public static String toFit(ObjectMapper om, String json, int max) {
        if (json == null || json.length() <= max) {
            return json;
        }
        String empty = wrap(om, json, 0);
        if (empty == null || empty.length() > max) {
            return minimal(json, max);
        }
        int preview = Math.min(json.length(), max - empty.length());
        for (int attempt = 0; attempt < MAX_ATTEMPTS && preview > 0; attempt++) {
            String candidate = wrap(om, json, preview);
            if (candidate == null) {
                break;
            }
            if (candidate.length() <= max) {
                return candidate;
            }
            // 이스케이프(따옴표·유니코드)로 넘친 만큼 미리보기를 줄인다
            preview -= Math.max(1, candidate.length() - max);
        }
        return minimal(json, max);
    }

    private static String wrap(ObjectMapper om, String json, int previewLen) {
        int n = previewLen;
        // 서로게이트 쌍을 반으로 자르면 짝 잃은 문자가 남는다
        if (n > 0 && n < json.length() && Character.isHighSurrogate(json.charAt(n - 1))) {
            n--;
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("_truncated", json.length());
        out.put("_preview", json.substring(0, n));
        try {
            return om.writeValueAsString(out);
        } catch (Exception e) {
            return null;
        }
    }

    /** 미리보기조차 못 담을 때의 최소형. 그것도 안 들어가면 빈 객체다 (파싱은 되어야 한다). */
    private static String minimal(String json, int max) {
        String s = "{\"_truncated\":" + json.length() + "}";
        return s.length() <= max ? s : "{}";
    }
}
