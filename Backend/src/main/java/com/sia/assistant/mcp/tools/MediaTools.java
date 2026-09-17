package com.sia.assistant.mcp.tools;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.context.ContextService;
import com.sia.assistant.control.input.SendInputService;
import com.sia.assistant.control.window.WindowService;
import com.sia.assistant.mcp.CallerContext;
import com.sia.assistant.mcp.McpResults;
import com.sia.assistant.mcp.RefResolver;
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
 * 폴백 자체가 성립하지 않는다. 유튜브든 아니든 좌·우 방향키를 보낸다.
 * 그래서 <b>배경 재생을 제어할 수 없는 유일한 media.* 도구</b>다: 나머지 넷은 시스템 미디어 키가
 * 재생 세션으로 가지만 방향키는 포커스를 쥔 창이 받는다. 영상 창이 앞이 아니면 winRef 로 지정한다.
 */
@Component
public class MediaTools {

    private static final int VK_SHIFT = 0x10;
    private static final long FOCUS_SETTLE_MS = 80;
    private static final int DEFAULT_SEEK_AMOUNT = 1;

    private final ToolGate gate;
    private final ContextService contextService;
    private final WindowService windowService;
    private final RefResolver refResolver;
    private final SendInputService sendInput;
    private final McpResults mcp;

    public MediaTools(ToolGate gate, ContextService contextService, WindowService windowService,
                      RefResolver refResolver, SendInputService sendInput, McpResults mcp) {
        this.gate = gate;
        this.contextService = contextService;
        this.windowService = windowService;
        this.refResolver = refResolver;
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
            @McpToolParam(required = false, description = "방향키를 누를 횟수 1~10 (생략 시 1)") Integer amount,
            @McpToolParam(required = false,
                    description = "영상 창의 ref(win:N). 그 창을 앞으로 가져온 뒤 방향키를 보낸다. "
                            + "생략하면 지금 앞에 있는 창이 받는다") String winRef) {
        return mcp.of(seekResult(dir, amount, winRef));
    }

    public ToolResult seekResult(String dir, Integer amount, String winRef) {
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("dir", dir);
        if (amount != null) {
            args.put("amount", amount);
        }
        if (winRef != null) {
            args.put("winRef", winRef);
        }
        return gate.run("media.seek", args, CallerContext.get(), () -> {
            String arrow = switch (dir == null ? "" : dir.trim().toLowerCase(Locale.ROOT)) {
                case "forward" -> "right";
                case "backward" -> "left";
                default -> throw new ApiException(ErrorCode.INVALID_REQUEST,
                        "지원하지 않는 이동 방향입니다: " + dir + " (forward|backward)");
            };
            // ★ 방향키는 포커스를 쥔 창이 받는다 — winRef 를 받았으면 먼저 그 창을 앞으로 가져온다.
            //   전면화에 실패하면 예외가 그대로 올라가 키를 보내지 않는다: 엉뚱한 앱에 방향키가 들어가느니
            //   실패로 돌려주는 편이 낫다 (조용히 남의 문서 커서를 옮기는 게 이 도구의 최악이다).
            if (winRef != null && !winRef.isBlank()) {
                windowService.focus(refResolver.resolveWindow(winRef));
                sleep(FOCUS_SETTLE_MS);
            }
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
