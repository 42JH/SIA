package com.sia.assistant.mcp;

/**
 * 도구 실행 결과의 <b>내부(도메인) 표현</b>. 게이트·기록·제스처 매크로가 전부 이 타입으로 말한다.
 *
 * <p>MCP 전송 표현은 이것이 아니다 — {@link McpResults} 가 사양 2025-11-25 의 CallToolResult
 * ({@code isError} + {@code content} + {@code structuredContent})로 옮긴다.
 * 여기의 ok=false 는 그쪽의 {@code isError:true}(Tool Execution Error)에 대응한다.
 *
 * <p>message 는 LLM 이 그대로 읽고 사용자에게 전달할 수 있는 한국어 문장이다.
 *
 * <p>"대기(pending)" 상태는 없다. BE 확인 게이트가 사라지면서 도구는 실행되거나 안 되거나 둘뿐이다 —
 * 파괴적 도구의 사용자 동의는 AI 가 호출 <b>전에</b> 받는다(docs/API.md §6.3).
 */
public record ToolResult(boolean ok, Object data, String code, String message) {

    public static ToolResult ok(Object data) {
        return new ToolResult(true, data, null, null);
    }

    public static ToolResult blocked(String code, String message) {
        return new ToolResult(false, null, code, message);
    }

    public static ToolResult failed(String message) {
        return new ToolResult(false, null, "FAILED", message);
    }
}
