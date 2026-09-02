package com.sia.assistant.mcp.tools;

import com.sia.assistant.control.system.SystemService;
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
 * system.lock — 화면 잠금 (와이어프레임 기능 선택 드롭다운 "시스템 > 화면 잠금").
 * 세션 잠금일 뿐 로그아웃·종료가 아니라 데이터 손실이 없다 — C 없음, S 만 받는다.
 */
@Component
public class SystemTools {

    private final ToolGate gate;
    private final SystemService systemService;
    private final McpResults mcp;

    public SystemTools(ToolGate gate, SystemService systemService, McpResults mcp) {
        this.gate = gate;
        this.systemService = systemService;
        this.mcp = mcp;
    }

    @McpTool(name = "system.lock", description = ToolCatalog.D_SYSTEM_LOCK,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult lock() {
        return mcp.of(lockResult());
    }

    public ToolResult lockResult() {
        return gate.run("system.lock", Map.of(), CallerContext.get(), systemService::lock);
    }
}
