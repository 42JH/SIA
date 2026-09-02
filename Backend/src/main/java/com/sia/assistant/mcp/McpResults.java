package com.sia.assistant.mcp;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * 내부 {@link ToolResult} → MCP {@code CallToolResult} 변환 (사양 2025-11-25, Tools §Tool Result·§Error Handling).
 *
 * <p>사양의 두 가지 오류 보고 방식 중 이 클래스가 만드는 것은 <b>Tool Execution Error</b> 뿐이다:
 * 세션 게이트·확인 게이트·인자 검증·실행 실패는 전부 "요청은 멀쩡했지만 도구가 일을 못 한" 경우라
 * {@code isError:true} 인 정상 결과로 돌려주고, LLM 이 읽고 스스로 고치거나 사용자에게 설명하게 한다.
 * Protocol Error(JSON-RPC error)는 여기서 만들지 않는다 — 모르는 도구 이름·깨진 요청은
 * MCP 서버가 우리 코드에 닿기 전에 거른다.
 *
 * <ul>
 *   <li>성공: {@code isError=false}, {@code structuredContent}=도구 데이터,
 *       {@code content}=그 JSON 직렬화 텍스트 한 장(사양의 backwards compatibility 권고)</li>
 *   <li>실패·차단: {@code isError=true},
 *       {@code content}=사용자에게 그대로 읽어 줄 한국어 문장,
 *       {@code structuredContent}={@code {code, message}}</li>
 * </ul>
 *
 * <p>★ "대기" 상태는 없다 — 도구는 실행되거나 안 되거나 둘뿐이다 (확인 게이트 제거, 2026-09-01).
 * 실패의 종류는 {@code structuredContent.code} 가 나른다.
 * outputSchema 는 선언하지 않는다(성공·실패의 구조가 다르다). 반환 타입이 {@code CallToolResult} 라
 * 애노테이션 계층도 스키마를 자동 생성하지 않는다.
 */
@Component
public class McpResults {

    private static final Logger log = LoggerFactory.getLogger(McpResults.class);

    /** 데이터가 없는 도구(window.focus, scroll.step 등)의 성공 텍스트. */
    private static final String OK_TEXT = "실행했습니다";
    private static final String FALLBACK_ERROR_TEXT = "도구 실행에 실패했습니다";

    private final ObjectMapper om;

    public McpResults(ObjectMapper om) {
        this.om = om;
    }

    public CallToolResult of(ToolResult result) {
        if (result == null) {
            return CallToolResult.builder()
                    .isError(true)
                    .addTextContent(FALLBACK_ERROR_TEXT)
                    .structuredContent(errorBody("FAILED", FALLBACK_ERROR_TEXT))
                    .build();
        }
        return result.ok() ? success(result) : failure(result);
    }

    private CallToolResult success(ToolResult result) {
        Object data = result.data();
        CallToolResult.Builder builder = CallToolResult.builder().isError(false);
        if (data == null) {
            return builder.addTextContent(OK_TEXT).build();
        }
        return builder.structuredContent(data).addTextContent(json(data)).build();
    }

    private CallToolResult failure(ToolResult result) {
        String message = result.message() == null || result.message().isBlank()
                ? FALLBACK_ERROR_TEXT
                : result.message();
        return CallToolResult.builder()
                .isError(true)
                .addTextContent(message)
                .structuredContent(errorBody(result.code(), message))
                .build();
    }

    private static Map<String, Object> errorBody(String code, String message) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("code", code == null ? "FAILED" : code);
        body.put("message", message);
        return body;
    }

    /** 텍스트 블록용 직렬화. 실패해도 결과를 죽이지 않는다 — 정본은 structuredContent 다. */
    private String json(Object data) {
        try {
            return om.writeValueAsString(data);
        } catch (Exception e) {
            log.warn("도구 데이터 직렬화 실패 — 텍스트 블록만 대체합니다", e);
            return OK_TEXT;
        }
    }
}
