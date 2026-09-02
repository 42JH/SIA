package com.sia.assistant.common;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

/**
 * REST 본문을 Jackson 2 {@link JsonNode} 로 읽는 유일한 통로.
 *
 * <p><b>왜 필요한가.</b> Boot 4 / Spring 7 의 HTTP 메시지 컨버터는 Jackson 3(tools.jackson)다.
 * 그런데 이 프로젝트의 내부 라우팅은 Jackson 2(com.fasterxml)의 {@code JsonNode} 를 쓴다
 * (config/JacksonConfig 참조). 그래서 {@code @RequestBody JsonNode} 로 받으면 컨버터가
 * 모르는 타입이라 {@code HttpMessageConversionException} 으로 500 이 난다 —
 * 본문을 {@code String} 으로 받아 Jackson 2 로 직접 파싱한다.
 *
 * <p>깨진 JSON 은 500 이 아니라 {@code INVALID_REQUEST} 다.
 */
public final class JsonBody {

    private JsonBody() {
    }

    /** 빈 본문은 null 을 준다 — "필수 필드가 없다"는 판정은 각 컨트롤러의 몫이다. */
    public static JsonNode parse(ObjectMapper om, String body) {
        if (body == null || body.isBlank()) {
            return null;
        }
        try {
            return om.readTree(body);
        } catch (Exception e) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "본문이 올바른 JSON 이 아닙니다");
        }
    }
}
