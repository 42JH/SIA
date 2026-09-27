package com.sia.assistant.mcp.tools;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.mcp.McpResults;
import com.sia.assistant.mcp.ToolCatalog;
import com.sia.assistant.mcp.ToolResult;
import com.sia.assistant.session.SessionService;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.function.Supplier;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.mcp.annotation.McpTool;
import org.springframework.stereotype.Component;

/**
 * session.extend / session.cancel —
 * 이 둘은 ToolGate 를 지나지 않고 SessionService 를 직접 호출한다.
 * (confirm.* 는 기록도 없다 — 원래 도구의 CONFIRM_PENDING/실행 두 행이 기록이다.)
 * 예외는 MCP 밖으로 던지지 않고 전부 ToolResult 로 환원한다.
 */
@Component
public class SessionTools {

    private static final Logger log = LoggerFactory.getLogger(SessionTools.class);

    private final SessionService sessionService;
    private final McpResults mcp;

    public SessionTools(SessionService sessionService, McpResults mcp) {
        this.sessionService = sessionService;
        this.mcp = mcp;
    }

    @McpTool(name = "session.extend", description = ToolCatalog.D_SESSION_EXTEND,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult extend() {
        return mcp.of(extendResult());
    }

    public ToolResult extendResult() {
        return guard("session.extend", () -> {
            Map<String, Object> renewed = sessionService.renew(null);
            Map<String, Object> data = new LinkedHashMap<>();
            data.put("remainingSec", renewed.get("remainingSec"));
            data.put("deadlineMs", renewed.get("deadlineMs"));
            return data;
        });
    }

    @McpTool(name = "session.cancel", description = ToolCatalog.D_SESSION_CANCEL,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult cancel() {
        return mcp.of(cancelResult());
    }

    public ToolResult cancelResult() {
        return guard("session.cancel", () -> {
            long id = sessionService.requireActive();
            return sessionService.end(id, "STOPPED");
        });
    }

    private ToolResult guard(String tool, Supplier<Object> action) {
        try {
            return ToolResult.ok(action.get());
        } catch (ApiException e) {
            // BlockedException(SESSION_REQUIRED) 등 — 코드와 문장을 그대로 전달
            return ToolResult.blocked(e.code.name(), e.getMessage());
        } catch (Exception e) {
            log.warn("{} 처리 실패", tool, e);
            return ToolResult.failed("요청 처리에 실패했습니다. 잠시 후 다시 시도해주세요");
        }
    }
}
