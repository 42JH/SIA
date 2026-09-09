package com.sia.assistant.mcp.tools;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.control.audio.AudioService;
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

/**
 * volume.step — VK_VOLUME_UP/DOWN 한 단계.
 * volume.set — Core Audio 로 0~100 절대값. 단계로는 못 맞추는 "30으로 해줘"가 이쪽이다.
 */
@Component
public class VolumeTools {

    private final ToolGate gate;
    private final SendInputService sendInput;
    private final AudioService audio;
    private final McpResults mcp;

    public VolumeTools(ToolGate gate, SendInputService sendInput, AudioService audio, McpResults mcp) {
        this.gate = gate;
        this.sendInput = sendInput;
        this.audio = audio;
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

    @McpTool(name = "volume.set", description = ToolCatalog.D_VOLUME_SET,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult set(
            @McpToolParam(required = true, description = "볼륨 값 0~100 (범위 밖은 잘라서 맞춤)") Integer level) {
        return mcp.of(setResult(level));
    }

    public ToolResult setResult(Integer level) {
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("level", level);
        return gate.run("volume.set", args, CallerContext.get(), () -> {
            // required 선언은 스키마일 뿐 서버가 대신 막아 주지 않는다 — 빠진 값은 여기서 환원한다
            if (level == null) {
                throw new ApiException(ErrorCode.INVALID_REQUEST, "볼륨 값(level)이 필요합니다 (0~100)");
            }
            AudioService.Volume volume = audio.set(level);
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("level", volume.level());
            out.put("muted", volume.muted());
            return out;
        });
    }
}
