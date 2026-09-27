package com.sia.assistant.mcp;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class ToolResultTest {

    @Test
    @DisplayName("ok 는 데이터만 싣고 코드·메시지는 비운다")
    void okCarriesOnlyData() {
        ToolResult r = ToolResult.ok("data");

        assertThat(r.ok()).isTrue();
        assertThat(r.data()).isEqualTo("data");
        assertThat(r.code()).isNull();
        assertThat(r.message()).isNull();
    }

    @Test
    @DisplayName("blocked 는 정책 코드와 메시지를 그대로 나른다")
    void blockedCarriesCodeAndMessage() {
        ToolResult r = ToolResult.blocked("SESSION_REQUIRED", "세션이 활성화되지 않았습니다");

        assertThat(r.ok()).isFalse();
        assertThat(r.code()).isEqualTo("SESSION_REQUIRED");
        assertThat(r.message()).isEqualTo("세션이 활성화되지 않았습니다");
    }

    @Test
    @DisplayName("failed 는 FAILED 코드로 고정된다")
    void failedUsesFixedCode() {
        ToolResult r = ToolResult.failed("도구 실행에 실패했습니다");

        assertThat(r.ok()).isFalse();
        assertThat(r.code()).isEqualTo("FAILED");
        assertThat(r.message()).isEqualTo("도구 실행에 실패했습니다");
    }
}
