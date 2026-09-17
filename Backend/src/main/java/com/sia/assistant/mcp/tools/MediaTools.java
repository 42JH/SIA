package com.sia.assistant.mcp.tools;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.context.ContextService;
import com.sia.assistant.control.input.SendInputService;
import com.sia.assistant.control.window.WindowService;
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
 * media.* — 다이어그램 01 의 분기: 포그라운드가 유튜브면 그 창을 포커스한 뒤 유튜브 단축키
 * (play_pause='k', mute='m', next=Shift+'n', prev=Shift+'p'), 아니면 시스템 미디어 키.
 * 유튜브 분기에서 시스템 미디어 키를 쓰면 백그라운드의 다른 플레이어가 반응할 수 있어 단축키가 정확하다.
 * ★ media.seek 만 이 분기 밖이다 — 시스템 미디어 키에 탐색(앞으로/뒤로)에 해당하는 가상 키가 없어
 * 폴백 자체가 성립하지 않는다. 유튜브든 아니든 포커스된 창에 좌·우 방향키를 보낸다.
 */
@Component
public class MediaTools {

    private static final int VK_SHIFT = 0x10;
    private static final long FOCUS_SETTLE_MS = 80;
    private static final int DEFAULT_SEEK_AMOUNT = 1;

    private final ToolGate gate;
    private final ContextService contextService;
    private final WindowService windowService;
    private final SendInputService sendInput;
    private final McpResults mcp;

    public MediaTools(ToolGate gate, ContextService contextService, WindowService windowService,
                      SendInputService sendInput, McpResults mcp) {
        this.gate = gate;
        this.contextService = contextService;
        this.windowService = windowService;
        this.sendInput = sendInput;
        this.mcp = mcp;
    }

    @McpTool(name = "media.play_pause", description = ToolCatalog.D_MEDIA_PLAY_PAUSE,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult playPause() {
        return mcp.of(playPauseResult());
    }

    public ToolResult playPauseResult() {
        return gate.run("media.play_pause", Map.of(), CallerContext.get(),
                () -> act('k', false, "PLAY_PAUSE"));
    }

    @McpTool(name = "media.mute_toggle", description = ToolCatalog.D_MEDIA_MUTE_TOGGLE,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult muteToggle() {
        return mcp.of(muteToggleResult());
    }

    public ToolResult muteToggleResult() {
        return gate.run("media.mute_toggle", Map.of(), CallerContext.get(),
                () -> act('m', false, "MUTE"));
    }

    @McpTool(name = "media.next", description = ToolCatalog.D_MEDIA_NEXT,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult next() {
        return mcp.of(nextResult());
    }

    public ToolResult nextResult() {
        return gate.run("media.next", Map.of(), CallerContext.get(), () -> act('n', true, "NEXT"));
    }

    @McpTool(name = "media.prev", description = ToolCatalog.D_MEDIA_PREV,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult prev() {
        return mcp.of(prevResult());
    }

    public ToolResult prevResult() {
        return gate.run("media.prev", Map.of(), CallerContext.get(), () -> act('p', true, "PREV"));
    }

    @McpTool(name = "media.seek", description = ToolCatalog.D_MEDIA_SEEK,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult seek(
            @McpToolParam(required = true, description = "이동 방향 (forward|backward)") String dir,
            @McpToolParam(required = false, description = "방향키를 누를 횟수 1~10 (생략 시 1)") Integer amount) {
        return mcp.of(seekResult(dir, amount));
    }

    public ToolResult seekResult(String dir, Integer amount) {
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("dir", dir);
        if (amount != null) {
            args.put("amount", amount);
        }
        return gate.run("media.seek", args, CallerContext.get(), () -> {
            String arrow = switch (dir == null ? "" : dir.trim().toLowerCase(Locale.ROOT)) {
                case "forward" -> "right";
                case "backward" -> "left";
                default -> throw new ApiException(ErrorCode.INVALID_REQUEST,
                        "지원하지 않는 이동 방향입니다: " + dir + " (forward|backward)");
            };
            sendInput.arrowKey(arrow, amount == null ? DEFAULT_SEEK_AMOUNT : amount);
            return null;
        });
    }

    private Object act(char youtubeKey, boolean shift, String mediaKey) {
        long fg = windowService.foregroundHwnd();
        if (fg != 0L && contextService.isYoutube(fg)) {
            windowService.focus(fg);
            sleep(FOCUS_SETTLE_MS);
            if (shift) {
                sendInput.shortcut(new int[]{VK_SHIFT}, sendInput.vkForChar(youtubeKey));
            } else {
                sendInput.key(youtubeKey);
            }
            return Map.of("via", "youtube");
        }
        sendInput.mediaKey(mediaKey);
        return Map.of("via", "media_key");
    }

    private static void sleep(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
