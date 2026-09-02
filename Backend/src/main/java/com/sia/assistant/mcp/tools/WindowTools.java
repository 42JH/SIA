package com.sia.assistant.mcp.tools;

import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.control.window.WindowService;
import com.sia.assistant.mcp.CallerContext;
import com.sia.assistant.mcp.McpResults;
import com.sia.assistant.mcp.RefResolver;
import com.sia.assistant.mcp.ToolCatalog;
import com.sia.assistant.mcp.ToolGate;
import com.sia.assistant.mcp.ToolResult;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.ai.mcp.annotation.McpTool;
import org.springframework.ai.mcp.annotation.McpToolParam;
import org.springframework.stereotype.Component;

/** window.* — winRef 는 항상 RefResolver 를 지나 hwnd 로 변환된다. */
@Component
public class WindowTools {

    private static final String WIN_REF_DESC = "대상 창의 ref (context.get 또는 window.list 가 준 win:N)";

    private final ToolGate gate;
    private final WindowService windowService;
    private final RefResolver refResolver;
    private final McpResults mcp;

    public WindowTools(ToolGate gate, WindowService windowService, RefResolver refResolver, McpResults mcp) {
        this.gate = gate;
        this.windowService = windowService;
        this.refResolver = refResolver;
        this.mcp = mcp;
    }

    @McpTool(name = "window.list", description = ToolCatalog.D_WINDOW_LIST,
            annotations = @McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false))
    public CallToolResult list() {
        return mcp.of(listResult());
    }

    public ToolResult listResult() {
        return gate.run("window.list", Map.of(), CallerContext.get(),
                () -> Map.of("windows", refResolver.refreshWindows()));
    }

    @McpTool(name = "window.focus", description = ToolCatalog.D_WINDOW_FOCUS,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult focus(@McpToolParam(required = true, description = WIN_REF_DESC) String winRef) {
        return mcp.of(focusResult(winRef));
    }

    public ToolResult focusResult(String winRef) {
        return gate.run("window.focus", args(winRef, null), CallerContext.get(), () -> {
            windowService.focus(refResolver.resolveWindow(winRef));
            return null;
        });
    }

    @McpTool(name = "window.minimize", description = ToolCatalog.D_WINDOW_MINIMIZE,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult minimize(@McpToolParam(required = true, description = WIN_REF_DESC) String winRef) {
        return mcp.of(minimizeResult(winRef));
    }

    public ToolResult minimizeResult(String winRef) {
        return gate.run("window.minimize", args(winRef, null), CallerContext.get(), () -> {
            windowService.minimize(refResolver.resolveWindow(winRef));
            return null;
        });
    }

    @McpTool(name = "window.maximize", description = ToolCatalog.D_WINDOW_MAXIMIZE,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult maximize(@McpToolParam(required = true, description = WIN_REF_DESC) String winRef) {
        return mcp.of(maximizeResult(winRef));
    }

    public ToolResult maximizeResult(String winRef) {
        return gate.run("window.maximize", args(winRef, null), CallerContext.get(), () -> {
            windowService.maximize(refResolver.resolveWindow(winRef));
            return null;
        });
    }

    @McpTool(name = "window.restore", description = ToolCatalog.D_WINDOW_RESTORE,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult restore(@McpToolParam(required = true, description = WIN_REF_DESC) String winRef) {
        return mcp.of(restoreResult(winRef));
    }

    public ToolResult restoreResult(String winRef) {
        return gate.run("window.restore", args(winRef, null), CallerContext.get(), () -> {
            windowService.restore(refResolver.resolveWindow(winRef));
            return null;
        });
    }

    @McpTool(name = "window.resize", description = ToolCatalog.D_WINDOW_RESIZE,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult resize(
            @McpToolParam(required = true, description = WIN_REF_DESC) String winRef,
            @McpToolParam(required = true,
                    description = "크기 프리셋 (LEFT_HALF|RIGHT_HALF|MAXIMIZE|RESTORE|CENTER)") String preset) {
        return mcp.of(resizeResult(winRef, preset));
    }

    public ToolResult resizeResult(String winRef, String preset) {
        return gate.run("window.resize", args(winRef, preset), CallerContext.get(), () -> {
            windowService.resize(refResolver.resolveWindow(winRef), preset);
            return null;
        });
    }

    // C 플래그 = "AI 가 호출 전 사용자 동의를 받아야 한다"는 선언이다. BE 는 보류하지 않는다.
    // MCP 표준 destructiveHint 로 나가므로 AI 는 우리끼리의 규약 없이 tools/list 에서 그대로 읽는다.
    @McpTool(name = "window.close", description = ToolCatalog.D_WINDOW_CLOSE,
            annotations = @McpTool.McpAnnotations(destructiveHint = true))
    public CallToolResult close(@McpToolParam(required = true, description = WIN_REF_DESC) String winRef) {
        return mcp.of(closeResult(winRef));
    }

    public ToolResult closeResult(String winRef) {
        return gate.run("window.close", args(winRef, null), CallerContext.get(), () -> {
            windowService.close(refResolver.resolveWindow(winRef));
            return null;
        });
    }

    @McpTool(name = "window.next", description = ToolCatalog.D_WINDOW_NEXT,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult next() {
        return mcp.of(nextResult());
    }

    public ToolResult nextResult() {
        return gate.run("window.next", Map.of(), CallerContext.get(), () -> cycle(1));
    }

    @McpTool(name = "window.prev", description = ToolCatalog.D_WINDOW_PREV,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult prev() {
        return mcp.of(prevResult());
    }

    public ToolResult prevResult() {
        return gate.run("window.prev", Map.of(), CallerContext.get(), () -> cycle(-1));
    }

    /** 스냅샷을 갱신한 뒤 포그라운드 기준으로 delta 만큼 이동한 창을 포커스한다. */
    private Object cycle(int delta) {
        List<Map<String, Object>> windows = refResolver.refreshWindows();
        List<WindowService.WindowInfo> snap = refResolver.current();
        if (snap.isEmpty()) {
            throw new BlockedException(ErrorCode.REF_NOT_FOUND, "전환할 창이 없습니다");
        }
        long fg = windowService.foregroundHwnd();
        int idx = -1;
        for (int i = 0; i < snap.size(); i++) {
            if (snap.get(i).hwnd() == fg) {
                idx = i;
                break;
            }
        }
        int target = idx < 0 ? 0 : Math.floorMod(idx + delta, snap.size());
        windowService.focus(snap.get(target).hwnd());
        return Map.of("focused", windows.get(target));
    }

    private static Map<String, Object> args(String winRef, String preset) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("winRef", winRef);
        if (preset != null) {
            m.put("preset", preset);
        }
        return m;
    }
}
