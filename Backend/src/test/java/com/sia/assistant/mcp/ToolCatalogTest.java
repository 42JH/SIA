package com.sia.assistant.mcp;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class ToolCatalogTest {

    @Test
    @DisplayName("카탈로그는 30개다 — tool 테이블의 원천")
    void catalogHas30Tools() {
        assertThat(ToolCatalog.all()).hasSize(30);
        // 확인 게이트가 사라지면서 confirm.* 두 개는 카탈로그에 없다
        assertThat(ToolCatalog.spec("confirm.accept")).isNull();
        assertThat(ToolCatalog.spec("confirm.reject")).isNull();
        // 와이어프레임 확정으로 들어온 두 도구 — 제스처 매크로(파일 실행·화면 잠금)의 목적지
        assertThat(ToolCatalog.spec("files.open").confirmRequired()).isFalse();
        assertThat(ToolCatalog.spec("system.lock").confirmRequired()).isFalse();
        // 흐름도 02 "캡처 결과물 저장·표시는 BE 소유" — 파일을 만들 뿐 지우지 않으므로 C 없음, S 만 받는다
        assertThat(ToolCatalog.spec("screen.capture").sessionRequired()).isTrue();
        assertThat(ToolCatalog.spec("screen.capture").confirmRequired()).isFalse();
        // 우상단·좌하단 두 점 영역 캡처 — screen.capture 와 같은 급 (파일만 만든다)
        assertThat(ToolCatalog.spec("screen.capture_region").sessionRequired()).isTrue();
        assertThat(ToolCatalog.spec("screen.capture_region").confirmRequired()).isFalse();
        // 절대값 볼륨 — 단계(volume.step)와 같은 급이다
        assertThat(ToolCatalog.spec("volume.set").sessionRequired()).isTrue();
        assertThat(ToolCatalog.spec("volume.set").confirmRequired()).isFalse();
        // 브라우저 검색 — 탭을 열 뿐 지우지 않으므로 C 없이 S 만 받는다 (확장 연결 여부와 무관하게 같다)
        assertThat(ToolCatalog.spec("browser.search").sessionRequired()).isTrue();
        assertThat(ToolCatalog.spec("browser.search").confirmRequired()).isFalse();
    }

    @Test
    @DisplayName("세션 없이 부를 수 있는 도구는 조회 계열 4개뿐이다")
    void onlyReadOnlyToolsSkipSession() {
        List<String> sessionFree = ToolCatalog.all().stream()
                .filter(spec -> !spec.sessionRequired())
                .map(ToolCatalog.ToolSpec::name)
                .toList();

        assertThat(sessionFree).containsExactlyInAnyOrder(
                "context.get", "app.list", "window.list", "explorer.items");
    }

    @Test
    @DisplayName("확인 게이트(C)는 파괴적인 두 도구에만 걸린다 — window.close · files.delete")
    void onlyDestructiveToolsRequireConfirm() {
        List<String> confirmRequired = ToolCatalog.all().stream()
                .filter(ToolCatalog.ToolSpec::confirmRequired)
                .map(ToolCatalog.ToolSpec::name)
                .toList();

        assertThat(confirmRequired).containsExactlyInAnyOrder("window.close", "files.delete");
        // C 는 BE 가 집행하는 관문이 아니라 "AI 가 호출 전 사용자 동의를 받아야 한다"는 선언이다
    }

    @Test
    @DisplayName("spec 은 이름으로 스펙을 찾고, 모르는 이름·null 은 예외 없이 null 을 준다")
    void specLookup() {
        ToolCatalog.ToolSpec spec = ToolCatalog.spec("window.close");
        assertThat(spec).isNotNull();
        assertThat(spec.sessionRequired()).isTrue();
        assertThat(spec.confirmRequired()).isTrue();

        assertThat(ToolCatalog.spec("no.such.tool")).isNull();
        assertThat(ToolCatalog.spec(null)).isNull();
    }

    @Test
    @DisplayName("모든 도구는 LLM 에 보여줄 설명을 갖는다")
    void everyToolHasDescription() {
        assertThat(ToolCatalog.all())
                .allSatisfy(spec -> assertThat(spec.description()).isNotBlank());
    }
}
