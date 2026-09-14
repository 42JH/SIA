package com.sia.assistant.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

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
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 내부 호출 파사드의 매핑 완전성. 제스처 매크로 스텝은 validateSteps 가 C 도구만 막고 저장하므로,
 * 카탈로그에 있는데 dispatch 에 분기가 없는 도구는 저장은 되고 실행은 항상 FAILED 로 떨어진다.
 * 도구를 추가할 때 이 테스트가 그 갭을 잡는다.
 */
class ToolInvokerTest {

    private BrowserTools browserTools;
    private ToolInvoker invoker;

    @BeforeEach
    void setUp() {
        browserTools = mock(BrowserTools.class);
        invoker = new ToolInvoker(mock(ContextTools.class), mock(AppTools.class), browserTools,
                mock(WindowTools.class), mock(ExplorerTools.class), mock(ScrollTools.class),
                mock(MediaTools.class), mock(VolumeTools.class), mock(FilesTools.class),
                mock(SystemTools.class), mock(ScreenTools.class), mock(SessionTools.class));
    }

    @Test
    @DisplayName("카탈로그의 모든 도구가 dispatch 분기를 가진다 — 알 수 없는 도구로 떨어지는 이름이 없다")
    void everyCatalogToolIsDispatchable() {
        List<String> unmapped = new ArrayList<>();
        for (ToolCatalog.ToolSpec spec : ToolCatalog.all()) {
            ToolResult result = invoker.invoke(spec.name(), Map.of(), Caller.GESTURE);
            // 목은 null 을 돌려주므로, 값이 있다면 그것은 default 분기의 실패 결과다
            if (result != null && !result.ok()) {
                unmapped.add(spec.name() + " → " + result.message());
            }
        }
        assertThat(unmapped).isEmpty();
    }

    @Test
    @DisplayName("browser.dom_text 는 BrowserTools 의 내부 결과 메서드로 간다")
    void domTextGoesToBrowserTools() {
        invoker.invoke("browser.dom_text", Map.of(), Caller.GESTURE);

        verify(browserTools).domTextResult();
    }

    @Test
    @DisplayName("모르는 이름은 예외 없이 FAILED 를 돌려준다")
    void unknownToolFails() {
        ToolResult result = invoker.invoke("no.such.tool", Map.of(), Caller.GESTURE);

        assertThat(result.ok()).isFalse();
        assertThat(result.message()).startsWith("알 수 없는 도구입니다");
    }
}
