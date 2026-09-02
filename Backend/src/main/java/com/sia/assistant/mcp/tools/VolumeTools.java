package com.sia.assistant.mcp.tools;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.control.input.SendInputService;
import com.sia.assistant.mcp.CallerContext;
import com.sia.assistant.mcp.McpResults;
import com.sia.assistant.mcp.ToolCatalog;
import com.sia.assistant.mcp.ToolGate;
import com.sia.assistant.mcp.ToolResult;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import org.springframework.ai.mcp.annotation.McpTool;
import org.springframework.ai.mcp.annotation.McpToolParam;
import org.springframework.stereotype.Component;

/** volume.step — VK_VOLUME_UP/DOWN 한 단계. */
@Component
public class VolumeTools {

    private final ToolGate gate;
    private final SendInputService sendInput;
    private final McpResults mcp;

    public VolumeTools(ToolGate gate, SendInputService sendInput, McpResults mcp) {
        this.gate = gate;
        this.sendInput = sendInput;
        this.mcp = mcp;
    }

    @McpTool(name = "volume.step", description = ToolCatalog.D_VOLUME_STEP,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult step(
            @McpToolParam(required = true, description = "볼륨 방향 (up|down)") String dir) {
        return mcp.of(stepResult(dir));
    }

    public ToolResult stepResult(String dir) {
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("dir", dir);
        return gate.run("volume.step", args, CallerContext.get(), () -> {
            String d = dir == null ? "" : dir.trim().toLowerCase(Locale.ROOT);
            switch (d) {
                case "up" -> sendInput.mediaKey("VOL_UP");
                case "down" -> sendInput.mediaKey("VOL_DOWN");
                default -> throw new ApiException(ErrorCode.INVALID_REQUEST,
                        "지원하지 않는 볼륨 방향입니다: " + dir + " (up|down)");
            }
            return null;
        });
    }
}
