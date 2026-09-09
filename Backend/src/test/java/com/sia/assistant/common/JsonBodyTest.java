package com.sia.assistant.common;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class JsonBodyTest {

    private final ObjectMapper om = new ObjectMapper();

    @Test
    @DisplayName("parse: 빈 본문은 null — 필수 판정은 컨트롤러 몫")
    void parseReturnsNullForBlank() {
        assertThat(JsonBody.parse(om, null)).isNull();
        assertThat(JsonBody.parse(om, "")).isNull();
        assertThat(JsonBody.parse(om, "   ")).isNull();
    }

    @Test
    @DisplayName("parse: 깨진 JSON 은 500 이 아니라 INVALID_REQUEST")
    void parseRejectsBrokenJson() {
        assertThatThrownBy(() -> JsonBody.parse(om, "{"))
                .isInstanceOf(ApiException.class)
                .satisfies(e -> assertThat(((ApiException) e).code).isEqualTo(ErrorCode.INVALID_REQUEST));
    }

    @Test
    @DisplayName("parseObject: 빈 본문·비객체 본문은 null 역참조(500)가 아니라 INVALID_REQUEST 다")
    void parseObjectRejectsBlankAndNonObject() {
        assertThatThrownBy(() -> JsonBody.parseObject(om, ""))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("비어");
        assertThatThrownBy(() -> JsonBody.parseObject(om, "[1, 2]"))
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("객체");
    }

    @Test
    @DisplayName("parseObject: 객체 본문은 그대로 돌려준다")
    void parseObjectReturnsObject() {
        assertThat(JsonBody.parseObject(om, "{\"name\":\"a\"}").path("name").asText()).isEqualTo("a");
    }
}
