package com.sia.assistant.mcp.tools;

import com.sia.assistant.context.ContextService;
import com.sia.assistant.mcp.CallerContext;
import com.sia.assistant.mcp.McpResults;
import com.sia.assistant.mcp.ToolCatalog;
import com.sia.assistant.mcp.ToolGate;
import com.sia.assistant.mcp.ToolResult;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import java.util.Map;
import org.springframework.ai.mcp.annotation.McpTool;
import org.springframework.stereotype.Component;

/**
 * context.get.
 * 각 도구는 두 겹이다: @McpTool 메서드가 MCP 전송용 CallToolResult 를 만들고,
 * 같은 이름 + Result 메서드가 내부 호출(ToolInvoker → 제스처 매크로)용 ToolResult 를 낸다.
 */
@Component
public class ContextTools {

    private final ToolGate gate;
    private final ContextService contextService;
    private final McpResults mcp;

    public ContextTools(ToolGate gate, ContextService contextService, McpResults mcp) {
        this.gate = gate;
        this.contextService = contextService;
        this.mcp = mcp;
    }

    @McpTool(name = "context.get", description = ToolCatalog.D_CONTEXT_GET,
            annotations = @McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false))
    public CallToolResult get() {
        return mcp.of(getResult());
    }

    public ToolResult getResult() {
        return gate.run("context.get", Map.of(), CallerContext.get(), contextService::snapshot);
    }
}
