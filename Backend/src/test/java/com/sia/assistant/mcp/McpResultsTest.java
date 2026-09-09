package com.sia.assistant.mcp;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import io.modelcontextprotocol.spec.McpSchema.TextContent;
import java.util.LinkedHashMap;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/** ToolResult -> CallToolResult 매핑 (MCP 사양 2025-11-25 Tools §Tool Result·§Error Handling). */
class McpResultsTest {

    private final McpResults mcp = new McpResults(new ObjectMapper());

    @SuppressWarnings("unchecked")
    private static Map<String, Object> structured(CallToolResult result) {
        return (Map<String, Object>) result.structuredContent();
    }

    private static String text(CallToolResult result) {
        assertThat(result.content()).hasSize(1);
        assertThat(result.content().get(0)).isInstanceOf(TextContent.class);
        return ((TextContent) result.content().get(0)).text();
    }

    @Test
    @DisplayName("성공은 isError=false 이고 데이터가 structuredContent 에 그대로 실린다")
    void successCarriesStructuredContent() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("via", "youtube");

        CallToolResult result = mcp.of(ToolResult.ok(data));

        assertThat(result.isError()).isFalse();
        assertThat(result.structuredContent()).isSameAs(data);
        assertThat(text(result)).isEqualTo("{\"via\":\"youtube\"}");
    }

    @Test
    @DisplayName("데이터 없는 성공은 structuredContent 를 비우고 텍스트만 남긴다")
    void successWithoutDataHasNoStructuredContent() {
        CallToolResult result = mcp.of(ToolResult.ok(null));

        assertThat(result.isError()).isFalse();
        assertThat(result.structuredContent()).isNull();
        assertThat(text(result)).isEqualTo("실행했습니다");
    }

    @Test
    @DisplayName("차단은 isError=true 이고 사용자 문장이 content, 코드가 structuredContent 에 간다")
    void blockedBecomesToolExecutionError() {
        CallToolResult result = mcp.of(
                ToolResult.blocked("SESSION_REQUIRED", "세션이 활성화되지 않았습니다"));

        assertThat(result.isError()).isTrue();
        assertThat(text(result)).isEqualTo("세션이 활성화되지 않았습니다");
        assertThat(structured(result))
                .containsEntry("code", "SESSION_REQUIRED")
                .containsEntry("message", "세션이 활성화되지 않았습니다")
                .containsKey("message");
    }

    @Test
    @DisplayName("실패는 FAILED 코드로 간다")
    void failedCarriesFailedCode() {
        CallToolResult result = mcp.of(ToolResult.failed("앱 실행에 실패했습니다. 잠시 후 다시 시도해주세요"));

        assertThat(result.isError()).isTrue();
        assertThat(structured(result)).containsEntry("code", "FAILED");
        assertThat(text(result)).isEqualTo("앱 실행에 실패했습니다. 잠시 후 다시 시도해주세요");
    }

    @Test
    @DisplayName("null 결과도 예외 없이 오류 결과로 환원된다")
    void nullResultBecomesError() {
        CallToolResult result = mcp.of(null);

        assertThat(result.isError()).isTrue();
        assertThat(structured(result)).containsEntry("code", "FAILED");
    }
}
