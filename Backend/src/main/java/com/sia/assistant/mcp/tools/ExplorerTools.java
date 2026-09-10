package com.sia.assistant.mcp.tools;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.control.explorer.ExplorerService;
import com.sia.assistant.control.window.WindowService;
import com.sia.assistant.mcp.CallerContext;
import com.sia.assistant.mcp.McpResults;
import com.sia.assistant.mcp.RefResolver;
import com.sia.assistant.mcp.ToolCatalog;
import com.sia.assistant.mcp.ToolGate;
import com.sia.assistant.mcp.ToolResult;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.ai.mcp.annotation.McpTool;
import org.springframework.ai.mcp.annotation.McpToolParam;
import org.springframework.stereotype.Component;

/**
 * explorer.items — "이 파일 삭제해줘" 류 발화에서 시선 영역의 파일 후보를 절대 경로로 바꿔 주는 유일한 통로.
 * 읽기 전용 컨텍스트 도구라 세션 없이도 호출 가능(S=0) — context.get·window.list 와 같은 급.
 */
@Component
public class ExplorerTools {

    private final ToolGate gate;
    private final RefResolver refResolver;
    private final WindowService windowService;
    private final ExplorerService explorerService;
    private final McpResults mcp;

    public ExplorerTools(ToolGate gate, RefResolver refResolver, WindowService windowService,
                         ExplorerService explorerService, McpResults mcp) {
        this.gate = gate;
        this.refResolver = refResolver;
        this.windowService = windowService;
        this.explorerService = explorerService;
        this.mcp = mcp;
    }

    @McpTool(name = "explorer.items", description = ToolCatalog.D_EXPLORER_ITEMS,
            annotations = @McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false))
    public CallToolResult items(
            @McpToolParam(required = false,
                    description = "탐색기 창의 ref (win:N — context.get/window.list 가 준 값). 생략하면 포그라운드 창")
            String winRef) {
        return mcp.of(itemsResult(winRef));
    }

    public ToolResult itemsResult(String winRef) {
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("winRef", winRef);
        return gate.run("explorer.items", args, CallerContext.get(), () -> {
            long hwnd;
            if (winRef == null || winRef.isBlank()) {
                hwnd = windowService.foregroundHwnd();
                if (hwnd == 0L) {
                    throw new ApiException(ErrorCode.INVALID_REQUEST, "포그라운드 창이 없습니다");
                }
            } else {
                hwnd = refResolver.resolveWindow(winRef);
            }
            return explorerService.items(hwnd);
        });
    }
}
