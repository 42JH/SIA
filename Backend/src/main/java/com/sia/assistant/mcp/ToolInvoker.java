package com.sia.assistant.mcp;

import com.sia.assistant.mcp.tools.AppTools;
import com.sia.assistant.mcp.tools.BrowserTools;
import com.sia.assistant.mcp.tools.ContextTools;
import com.sia.assistant.mcp.tools.ExplorerTools;
import com.sia.assistant.mcp.tools.FilesTools;
import com.sia.assistant.mcp.tools.MediaTools;
import com.sia.assistant.mcp.tools.ScreenTools;
import com.sia.assistant.mcp.tools.ScrollTools;
import com.sia.assistant.mcp.tools.SessionTools;
import com.sia.assistant.mcp.tools.SystemTools;
import com.sia.assistant.mcp.tools.VolumeTools;
import com.sia.assistant.mcp.tools.WindowTools;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * 도구 이름 → 도구 메서드 호출 매핑 파사드.
 * GestureExecutor 처럼 MCP 전송 계층을 거치지 않는 서버 내부 호출자가 쓴다.
 * ★ 각 Tools 빈의 @McpTool 메서드가 아니라 그 짝인 ...Result 메서드를 부른다 —
 * 내부 경로는 CallToolResult(전송 표현)가 아니라 ToolResult(도메인 표현)를 그대로 쓴다.
 * 각 Tools 빈의 메서드가 이미 ToolGate.run(...) 으로 감싸져 있으므로
 * 여기서는 caller 를 ThreadLocal 에 심고(도구 메서드가 CallerContext.get() 으로 읽는다) 호출만 한다.
 */
@Component
public class ToolInvoker {

    private static final Logger log = LoggerFactory.getLogger(ToolInvoker.class);

    private final ContextTools contextTools;
    private final AppTools appTools;
    private final BrowserTools browserTools;
    private final WindowTools windowTools;
    private final ExplorerTools explorerTools;
    private final ScrollTools scrollTools;
    private final MediaTools mediaTools;
    private final VolumeTools volumeTools;
    private final FilesTools filesTools;
    private final SystemTools systemTools;
    private final ScreenTools screenTools;
    private final SessionTools sessionTools;

    public ToolInvoker(ContextTools contextTools, AppTools appTools, BrowserTools browserTools,
                       WindowTools windowTools,
                       ExplorerTools explorerTools, ScrollTools scrollTools, MediaTools mediaTools,
                       VolumeTools volumeTools, FilesTools filesTools, SystemTools systemTools,
                       ScreenTools screenTools, SessionTools sessionTools) {
        this.screenTools = screenTools;
        this.contextTools = contextTools;
        this.appTools = appTools;
        this.browserTools = browserTools;
        this.windowTools = windowTools;
        this.explorerTools = explorerTools;
        this.scrollTools = scrollTools;
        this.mediaTools = mediaTools;
        this.volumeTools = volumeTools;
        this.filesTools = filesTools;
        this.systemTools = systemTools;
        this.sessionTools = sessionTools;
    }

    public ToolResult invoke(String tool, Map<String, Object> args, Caller caller) {
        // 실행 스레드가 WS/Executor 스레드라 ThreadLocal 기본값(LLM)일 수 있다 — 반드시 심고 반드시 지운다.
        CallerContext.set(caller);
        try {
            return dispatch(tool, args);
        } catch (Exception e) {
            // 도구 메서드는 ToolGate 가 예외를 삼키므로 여기 오는 건 매핑/전처리 실패다.
            log.warn("도구 내부 호출 실패: {}", tool, e);
            return ToolResult.failed("도구 실행에 실패했습니다: " + tool);
        } finally {
            CallerContext.clear();
        }
    }

    private ToolResult dispatch(String tool, Map<String, Object> args) {
        return switch (tool) {
            case "context.get" -> contextTools.getResult();
            case "app.list" -> appTools.listResult();
            case "app.launch" -> appTools.launchResult(str(args, "appRef"));
            case "browser.search" -> browserTools.searchResult(str(args, "query"));
            case "window.list" -> windowTools.listResult();
            case "window.focus" -> windowTools.focusResult(str(args, "winRef"));
            case "window.minimize" -> windowTools.minimizeResult(str(args, "winRef"));
            case "window.maximize" -> windowTools.maximizeResult(str(args, "winRef"));
            case "window.restore" -> windowTools.restoreResult(str(args, "winRef"));
            case "window.resize" -> windowTools.resizeResult(str(args, "winRef"), str(args, "preset"));
            case "window.close" -> windowTools.closeResult(str(args, "winRef"));
            case "window.next" -> windowTools.nextResult();
            case "window.prev" -> windowTools.prevResult();
            case "explorer.items" -> explorerTools.itemsResult(str(args, "winRef"));
            case "scroll.step" -> scrollTools.stepResult(str(args, "dir"), intOrNull(args, "amount"));
            case "media.play_pause" -> mediaTools.playPauseResult();
            case "media.mute_toggle" -> mediaTools.muteToggleResult();
            case "media.next" -> mediaTools.nextResult();
            case "media.prev" -> mediaTools.prevResult();
            case "volume.step" -> volumeTools.stepResult(str(args, "dir"));
            case "volume.set" -> volumeTools.setResult(intOrNull(args, "level"));
            case "files.open" -> filesTools.openResult(str(args, "path"));
            case "files.delete" -> filesTools.deleteResult(strList(args, "paths"));
            case "files.save" -> filesTools.saveResult(str(args, "name"), str(args, "content"));
            case "system.lock" -> systemTools.lockResult();
            case "screen.capture" -> screenTools.captureResult(str(args, "winRef"));
            case "screen.capture_region" -> screenTools.captureRegionResult(
                    intOrNull(args, "x1"), intOrNull(args, "y1"), intOrNull(args, "x2"), intOrNull(args, "y2"));
            case "session.extend" -> sessionTools.extendResult();
            case "session.cancel" -> sessionTools.cancelResult();
            default -> ToolResult.failed("알 수 없는 도구입니다: " + tool);
        };
    }

    private static String str(Map<String, Object> args, String key) {
        Object v = args == null ? null : args.get(key);
        return v == null ? null : String.valueOf(v);
    }

    private static Integer intOrNull(Map<String, Object> args, String key) {
        Object v = args == null ? null : args.get(key);
        if (v == null) {
            return null;
        }
        if (v instanceof Number n) {
            return n.intValue();
        }
        try {
            return Integer.parseInt(String.valueOf(v));
        } catch (NumberFormatException e) {
            return null;
        }
    }

    private static List<String> strList(Map<String, Object> args, String key) {
        Object v = args == null ? null : args.get(key);
        if (v instanceof List<?> l) {
            return l.stream().map(String::valueOf).toList();
        }
        return List.of();
    }
}
