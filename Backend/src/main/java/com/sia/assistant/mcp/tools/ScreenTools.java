package com.sia.assistant.mcp.tools;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.control.screen.CaptureService;
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
 * screen.capture — 화면(또는 창) 캡처를 PNG 로 저장하고 FE 에 표시를 맡긴다 (흐름도 02 "저장·표시는 BE 소유").
 * screen.capture_region — 좌상단 (x1, y1) · 우하단 (x2, y2) 두 점이 감싸는 영역만 같은 방식으로 저장한다.
 * 둘 다 파일을 새로 만들 뿐 아무것도 지우지 않는다 — C 없음, S 만 받는다. 제스처 매크로에 넣을 수 있다.
 */
@Component
public class ScreenTools {

    private static final String MISSING_COORDS_MESSAGE = "캡처 영역의 좌표 네 개(x1, y1, x2, y2)가 모두 필요합니다";

    private final ToolGate gate;
    private final RefResolver refResolver;
    private final CaptureService captureService;
    private final McpResults mcp;

    public ScreenTools(ToolGate gate, RefResolver refResolver, CaptureService captureService, McpResults mcp) {
        this.gate = gate;
        this.refResolver = refResolver;
        this.captureService = captureService;
        this.mcp = mcp;
    }

    @McpTool(name = "screen.capture", description = ToolCatalog.D_SCREEN_CAPTURE,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult capture(
            @McpToolParam(required = false,
                    description = "캡처할 창의 ref (win:N — context.get/window.list 가 준 값). 생략하면 전체 화면")
            String winRef) {
        return mcp.of(captureResult(winRef));
    }

    public ToolResult captureResult(String winRef) {
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("winRef", winRef);
        return gate.run("screen.capture", args, CallerContext.get(), () -> {
            Long hwnd = (winRef == null || winRef.isBlank()) ? null : refResolver.resolveWindow(winRef);
            return captureService.capture(hwnd);
        });
    }

    @McpTool(name = "screen.capture_region", description = ToolCatalog.D_SCREEN_CAPTURE_REGION,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult captureRegion(
            @McpToolParam(required = true, description = "좌상단 모서리의 x 좌표 (가상 스크린 물리 픽셀)") Integer x1,
            @McpToolParam(required = true, description = "좌상단 모서리의 y 좌표 (가상 스크린 물리 픽셀)") Integer y1,
            @McpToolParam(required = true, description = "우하단 모서리의 x 좌표 (가상 스크린 물리 픽셀)") Integer x2,
            @McpToolParam(required = true, description = "우하단 모서리의 y 좌표 (가상 스크린 물리 픽셀)") Integer y2) {
        return mcp.of(captureRegionResult(x1, y1, x2, y2));
    }

    public ToolResult captureRegionResult(Integer x1, Integer y1, Integer x2, Integer y2) {
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("x1", x1);
        args.put("y1", y1);
        args.put("x2", x2);
        args.put("y2", y2);
        return gate.run("screen.capture_region", args, CallerContext.get(), () -> {
            // required 선언은 스키마일 뿐 서버가 대신 막아 주지 않는다 — 빠진 좌표는 여기서 FAILED 로 환원한다
            if (x1 == null || y1 == null || x2 == null || y2 == null) {
                throw new ApiException(ErrorCode.INVALID_REQUEST, MISSING_COORDS_MESSAGE);
            }
            return captureService.captureRegion(x1, y1, x2, y2);
        });
    }
}
