package com.sia.assistant.mcp;

import com.sia.assistant.common.Times;
import io.modelcontextprotocol.server.McpSyncServer;
import io.modelcontextprotocol.spec.McpSchema;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.core.annotation.Order;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

/**
 * 기동 시 카탈로그 → tool 테이블 UPSERT — tool 행의 유일한 생성 경로다 (마이그레이션은 시드하지 않는다).
 * available 갱신, DELETE 금지 — tool_call FK 가 행 존속을 요구한다.
 * MCP 서버에 등록된 @McpTool 이 카탈로그에 없으면 코드가 어긋난 것이므로 기동을 세운다.
 * DefaultMappingBootstrap(@Order 5)이 이 동기화(@Order 0) 뒤에 기본 제스처를 넣는다 — gesture_step FK 전제.
 */
@Component
public class ToolCatalogSync {

    private static final Logger log = LoggerFactory.getLogger(ToolCatalogSync.class);

    private static final String UPSERT_WITH_SCHEMA = """
            INSERT INTO tool (name, description, input_schema_json, session_required, confirm_required, available, synced_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
              description = excluded.description,
              input_schema_json = excluded.input_schema_json,
              session_required = excluded.session_required,
              confirm_required = excluded.confirm_required,
              available = excluded.available,
              synced_at = excluded.synced_at
            """;

    /** 등록되지 않은 도구는 기존 input_schema_json 을 보존한다 (available 만 내린다). */
    private static final String UPSERT_KEEP_SCHEMA = """
            INSERT INTO tool (name, description, input_schema_json, session_required, confirm_required, available, synced_at)
            VALUES (?, ?, '{}', ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
              description = excluded.description,
              session_required = excluded.session_required,
              confirm_required = excluded.confirm_required,
              available = excluded.available,
              synced_at = excluded.synced_at
            """;

    private final JdbcTemplate jdbc;
    private final ObjectProvider<McpSyncServer> mcpServerProvider;
    private final ObjectMapper om;

    public ToolCatalogSync(JdbcTemplate jdbc, ObjectProvider<McpSyncServer> mcpServerProvider, ObjectMapper om) {
        this.jdbc = jdbc;
        this.mcpServerProvider = mcpServerProvider;
        this.om = om;
    }

    @EventListener(ApplicationReadyEvent.class)
    @Order(0)
    public void sync() {
        McpSyncServer server = mcpServerProvider.getIfAvailable();
        Map<String, McpSchema.Tool> registered = new LinkedHashMap<>();
        if (server == null) {
            // MCP 전송이 없어도 ToolInvoker(제스처 경로)로는 호출 가능하므로 available 을 내리지 않는다
            log.warn("McpSyncServer 빈이 없어 등록 도구를 확인하지 못했습니다 — 카탈로그 기준으로 동기화합니다");
        } else {
            for (McpSchema.Tool tool : server.listTools()) {
                if (ToolCatalog.spec(tool.name()) == null) {
                    throw new IllegalStateException(
                            "카탈로그에 없는 도구가 MCP 서버에 등록되었습니다: " + tool.name()
                                    + " — ToolCatalog 와 @McpTool 이 어긋났습니다. 기동을 중단합니다");
                }
                registered.put(tool.name(), tool);
            }
        }

        String now = Times.now();
        int availableCount = 0;
        for (ToolCatalog.ToolSpec spec : ToolCatalog.all()) {
            McpSchema.Tool tool = registered.get(spec.name());
            boolean available = server == null || tool != null;
            if (available) {
                availableCount++;
            }
            String schemaJson = schemaJsonOf(tool);
            if (schemaJson != null) {
                jdbc.update(UPSERT_WITH_SCHEMA, spec.name(), spec.description(), schemaJson,
                        spec.sessionRequired() ? 1 : 0, spec.confirmRequired() ? 1 : 0,
                        available ? 1 : 0, now);
            } else {
                jdbc.update(UPSERT_KEEP_SCHEMA, spec.name(), spec.description(),
                        spec.sessionRequired() ? 1 : 0, spec.confirmRequired() ? 1 : 0,
                        available ? 1 : 0, now);
            }
        }
        log.info("도구 카탈로그 동기화 완료 — 카탈로그 {}개 중 {}개 available", ToolCatalog.all().size(), availableCount);
    }

    private String schemaJsonOf(McpSchema.Tool tool) {
        if (tool == null || tool.inputSchema() == null) {
            return null;
        }
        try {
            return om.writeValueAsString(tool.inputSchema());
        } catch (Exception e) {
            log.warn("도구 {} 의 입력 스키마 직렬화에 실패해 기존 값을 유지합니다", tool.name(), e);
            return null;
        }
    }
}
