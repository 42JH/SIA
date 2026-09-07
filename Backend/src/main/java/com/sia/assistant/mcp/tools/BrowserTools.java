package com.sia.assistant.mcp.tools;

import com.sia.assistant.control.process.BrowserSearchService;
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

/**
 * browser.search — 기본 브라우저로 검색어를 찾거나 주소를 연다.
 * 탭을 새로 열 뿐 아무것도 지우지 않으므로 C 는 없고 S 만 받는다. 제스처 매크로에 넣을 수 있다.
 * 확장 연결 여부에 따라 여는 경로가 갈리는 것은 BrowserSearchService 가 안에서 판단한다 —
 * 도구 표면에서는 반환의 via · domAvailable 두 필드로만 드러난다.
 */
@Component
public class BrowserTools {

    private final ToolGate gate;
    private final BrowserSearchService browserSearchService;
    private final McpResults mcp;

    public BrowserTools(ToolGate gate, BrowserSearchService browserSearchService, McpResults mcp) {
        this.gate = gate;
        this.browserSearchService = browserSearchService;
        this.mcp = mcp;
    }

    @McpTool(name = "browser.search", description = ToolCatalog.D_BROWSER_SEARCH,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult search(
            @McpToolParam(required = true,
                    description = "검색어, 또는 http:// · https:// 로 시작하는 주소. 그 외 스킴은 받지 않습니다")
            String query) {
        return mcp.of(searchResult(query));
    }

    public ToolResult searchResult(String query) {
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("query", query);
        return gate.run("browser.search", args, CallerContext.get(),
                () -> browserSearchService.search(query));
    }
}
