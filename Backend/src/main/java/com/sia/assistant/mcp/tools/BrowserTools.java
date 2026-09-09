package com.sia.assistant.mcp.tools;

import com.sia.assistant.control.process.BrowserSearchService;
import com.sia.assistant.domtext.DomTextService;
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
 * 브라우저 도구 둘 — 탭을 열고(browser.search), 지금 보고 있는 페이지를 읽는다(browser.dom_text).
 * 둘 다 아무것도 지우지 않으므로 C 는 없고 S 만 받는다. browser.search 는 제스처 매크로에 넣을 수 있다.
 *
 * <p>둘 다 확장 연결 여부에 따라 안에서 경로가 갈리고, 도구 표면에서는 반환의 via 로만 드러난다 —
 * 여는 쪽은 BrowserSearchService, 읽는 쪽은 DomTextService 가 판단한다.
 */
@Component
public class BrowserTools {

    private final ToolGate gate;
    private final BrowserSearchService browserSearchService;
    private final DomTextService domTextService;
    private final McpResults mcp;

    public BrowserTools(ToolGate gate, BrowserSearchService browserSearchService,
                        DomTextService domTextService, McpResults mcp) {
        this.gate = gate;
        this.browserSearchService = browserSearchService;
        this.domTextService = domTextService;
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

    /** 인자가 없다 — 어느 페이지를 읽을지는 BE 가 정한다 (활성 탭 · 포그라운드 브라우저 창). */
    @McpTool(name = "browser.dom_text", description = ToolCatalog.D_BROWSER_DOM_TEXT,
            annotations = @McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false))
    public CallToolResult domText() {
        return mcp.of(domTextResult());
    }

    public ToolResult domTextResult() {
        return gate.run("browser.dom_text", Map.of(), CallerContext.get(),
                domTextService::read);
    }
}
