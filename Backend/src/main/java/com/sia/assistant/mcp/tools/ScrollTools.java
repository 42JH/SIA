package com.sia.assistant.mcp.tools;

import com.sia.assistant.control.input.SendInputService;
import com.sia.assistant.mcp.CallerContext;
import com.sia.assistant.mcp.McpResults;
import com.sia.assistant.mcp.ToolCatalog;
import com.sia.assistant.mcp.ToolGate;
import com.sia.assistant.mcp.ToolResult;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.ai.mcp.annotation.McpTool;
import org.springframework.ai.mcp.annotation.McpToolParam;
import org.springframework.stereotype.Component;

/** scroll.step — 휠 합성 입력. amount 생략 시 3클릭. */
@Component
public class ScrollTools {

    private static final int DEFAULT_AMOUNT = 3;

    private final ToolGate gate;
    private final SendInputService sendInput;
    private final McpResults mcp;

    public ScrollTools(ToolGate gate, SendInputService sendInput, McpResults mcp) {
        this.gate = gate;
        this.sendInput = sendInput;
        this.mcp = mcp;
    }

    @McpTool(name = "scroll.step", description = ToolCatalog.D_SCROLL_STEP,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult step(
            @McpToolParam(required = true, description = "스크롤 방향 (up|down|left|right)") String dir,
            @McpToolParam(required = false, description = "스크롤 양 1~10 (생략 시 3)") Integer amount) {
        return mcp.of(stepResult(dir, amount));
    }

    public ToolResult stepResult(String dir, Integer amount) {
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("dir", dir);
        if (amount != null) {
            args.put("amount", amount);
        }
        return gate.run("scroll.step", args, CallerContext.get(), () -> {
            sendInput.scroll(dir, amount == null ? DEFAULT_AMOUNT : amount);
            return null;
        });
    }
}
