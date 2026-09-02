package com.sia.assistant.mcp.tools;

import com.sia.assistant.control.files.FileOpenService;
import com.sia.assistant.control.files.FileSaveService;
import com.sia.assistant.control.files.TrashService;
import com.sia.assistant.mcp.CallerContext;
import com.sia.assistant.mcp.McpResults;
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

/**
 * files.delete / files.save.
 * files.delete 는 카탈로그에서 유일하게 사용자 데이터를 없애는 도구다 — 확인 게이트(C)를 지난다.
 *   실행이 휴지통 이동뿐이라도 paths 는 샌드박스가 없는 절대 경로이고, 디렉터리를 주면 통째로 옮겨진다.
 *   휴지통이 항상 복구를 보장하지도 않는다 (용량 초과분은 영구 삭제, 네트워크·이동식 드라이브는 미경유).
 * files.save 는 C 가 없다 — ~/Documents/SIA/ 안에만 쓰고 중복이면 " (1)" 을 붙여 덮어쓰지 않는다.
 */
@Component
public class FilesTools {

    private final ToolGate gate;
    private final TrashService trashService;
    private final FileSaveService fileSaveService;
    private final FileOpenService fileOpenService;
    private final McpResults mcp;

    public FilesTools(ToolGate gate, TrashService trashService, FileSaveService fileSaveService,
                      FileOpenService fileOpenService, McpResults mcp) {
        this.gate = gate;
        this.trashService = trashService;
        this.fileSaveService = fileSaveService;
        this.fileOpenService = fileOpenService;
        this.mcp = mcp;
    }

    // 열기만 하고 내용을 바꾸지 않는다 — C 없음. 제스처 "파일 실행" 블록의 목적지 (와이어프레임 5-1/5-2).
    @McpTool(name = "files.open", description = ToolCatalog.D_FILES_OPEN,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult open(
            @McpToolParam(required = true, description = "기본 프로그램으로 열 파일의 절대 경로") String path) {
        return mcp.of(openResult(path));
    }

    public ToolResult openResult(String path) {
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("path", path);
        return gate.run("files.open", args, CallerContext.get(),
                () -> fileOpenService.open(path));
    }

    // C 플래그 = "AI 가 호출 전 사용자 동의를 받아야 한다"는 선언이다. BE 는 보류하지 않는다.
    // MCP 표준 destructiveHint 로 나가므로 AI 는 우리끼리의 규약 없이 tools/list 에서 그대로 읽는다.
    @McpTool(name = "files.delete", description = ToolCatalog.D_FILES_DELETE,
            annotations = @McpTool.McpAnnotations(destructiveHint = true))
    public CallToolResult delete(
            @McpToolParam(required = true, description = "휴지통으로 이동할 파일의 절대 경로 목록") List<String> paths) {
        return mcp.of(deleteResult(paths));
    }

    public ToolResult deleteResult(List<String> paths) {
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("paths", paths);
        return gate.run("files.delete", args, CallerContext.get(),
                () -> trashService.moveToTrash(paths));
    }

    @McpTool(name = "files.save", description = ToolCatalog.D_FILES_SAVE,
            annotations = @McpTool.McpAnnotations(destructiveHint = false))
    public CallToolResult save(
            @McpToolParam(required = true, description = "저장할 파일 이름 (예: 메모.txt)") String name,
            @McpToolParam(required = true, description = "파일에 저장할 텍스트 내용") String content) {
        return mcp.of(saveResult(name, content));
    }

    public ToolResult saveResult(String name, String content) {
        Map<String, Object> args = new LinkedHashMap<>();
        args.put("name", name);
        args.put("content", content);
        return gate.run("files.save", args, CallerContext.get(),
                () -> fileSaveService.save(name, content));
    }
}
