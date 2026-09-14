package com.sia.assistant.mcp.tools;

import com.sia.assistant.context.ContextService;
import com.sia.assistant.control.process.AppLaunchService;
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

/** app.list / app.launch */
@Component
public class AppTools {

    private final ToolGate gate;
    private final ContextService contextService;
    private final AppLaunchService appLaunchService;
    private final RefResolver refResolver;
    private final McpResults mcp;

    public AppTools(ToolGate gate, ContextService contextService, AppLaunchService appLaunchService,
                    RefResolver refResolver, McpResults mcp) {
        this.gate = gate;
        this.contextService = contextService;
        this.appLaunchService = appLaunchService;
        this.refResolver = refResolver;
        this.mcp = mcp;
    }

    @McpTool(name = "app.list", description = ToolCatalog.D_APP_LIST,
            annotations = @McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false))
    public CallToolResult list() {
        return mcp.of(listResult());
    }

    public ToolResult listResult() {
        return gate.run("app.list", Map.of(), CallerContext.get(),
                () -> Map.of("apps", contextService.apps()));
    }

    @McpTool(name = "app.launch", description = ToolCatalog.D_APP_LAUNCH,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult launch(
            @McpToolParam(required = true, description = "실행할 앱의 ref (app.list 가 준 app:키)") String appRef) {
        return mcp.of(launchResult(appRef));
    }

    public ToolResult launchResult(String appRef) {
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("appRef", appRef);
        return gate.run("app.launch", args, CallerContext.get(),
                () -> appLaunchService.launch(refResolver.resolveAppKey(appRef)));
    }
}
