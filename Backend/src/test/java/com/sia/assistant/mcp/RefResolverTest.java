package com.sia.assistant.mcp;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.control.window.WindowService;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class RefResolverTest {

    private WindowService windowService;
    private RefResolver resolver;

    @BeforeEach
    void setUp() {
        windowService = mock(WindowService.class);
        resolver = new RefResolver(windowService);
    }

    private void givenWindows() {
        when(windowService.list()).thenReturn(List.of(
                new WindowService.WindowInfo(100L, "메모장", "notepad", "NORMAL"),
                new WindowService.WindowInfo(200L, "크롬", "chrome", "MAXIMIZED")));
        resolver.refreshWindows();
    }

    @Test
    @DisplayName("refreshWindows 는 ref 를 1부터 매기고 hwnd 는 절대 싣지 않는다")
    void refreshHidesHwnd() {
        when(windowService.list()).thenReturn(List.of(
                new WindowService.WindowInfo(100L, "메모장", "notepad", "NORMAL"),
                new WindowService.WindowInfo(200L, "크롬", "chrome", "MAXIMIZED")));

        List<Map<String, Object>> out = resolver.refreshWindows();

        assertThat(out).hasSize(2);
        assertThat(out.get(0))
                .containsEntry("ref", "win:1")
                .containsEntry("title", "메모장")
                .containsEntry("app", "notepad")
                .containsEntry("state", "NORMAL");
        assertThat(out.get(1)).containsEntry("ref", "win:2");
        assertThat(out).allSatisfy(entry ->
                assertThat(entry.keySet()).containsExactly("ref", "title", "app", "state"));
    }

    @Test
    @DisplayName("살아 있는 창의 win:N 은 hwnd 로 풀린다")
    void resolvesAliveWindow() {
        givenWindows();
        when(windowService.isAlive(200L)).thenReturn(true);

        assertThat(resolver.resolveWindow("win:2")).isEqualTo(200L);
    }

    @Test
    @DisplayName("스냅샷 이후 죽은 창은 REF_NOT_FOUND 다")
    void deadWindowIsNotFound() {
        givenWindows();
        when(windowService.isAlive(100L)).thenReturn(false);

        assertThatThrownBy(() -> resolver.resolveWindow("win:1"))
                .isInstanceOfSatisfying(BlockedException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.REF_NOT_FOUND));
    }

    @Test
    @DisplayName("범위 밖·형식 오류·null ref 는 전부 REF_NOT_FOUND 다")
    void invalidRefsAreNotFound() {
        givenWindows();

        for (String bad : new String[]{"win:0", "win:3", "win:-1", "win:abc", "abc", "app:chrome"}) {
            assertThatThrownBy(() -> resolver.resolveWindow(bad))
                    .as("ref=%s", bad)
                    .isInstanceOfSatisfying(BlockedException.class,
                            e -> assertThat(e.code).isEqualTo(ErrorCode.REF_NOT_FOUND));
        }
        assertThatThrownBy(() -> resolver.resolveWindow(null))
                .isInstanceOf(BlockedException.class);
    }

    @Test
    @DisplayName("스냅샷을 갱신한 적 없으면 어떤 win:N 도 풀리지 않는다")
    void emptySnapshotResolvesNothing() {
        assertThatThrownBy(() -> resolver.resolveWindow("win:1"))
                .isInstanceOf(BlockedException.class);
    }

    @Test
    @DisplayName("win: 뒤 공백은 관용적으로 받는다")
    void winRefToleratesWhitespace() {
        givenWindows();
        when(windowService.isAlive(100L)).thenReturn(true);

        assertThat(resolver.resolveWindow("  win: 1 ")).isEqualTo(100L);
    }

    @Test
    @DisplayName("app ref 는 접두사가 있든 없든 키만 남긴다")
    void appRefStripsPrefix() {
        assertThat(resolver.resolveAppKey("app:chrome")).isEqualTo("chrome");
        assertThat(resolver.resolveAppKey("chrome")).isEqualTo("chrome");
        assertThat(resolver.resolveAppKey(" app: calc ")).isEqualTo("calc");
    }

    @Test
    @DisplayName("빈 app ref 는 REF_NOT_FOUND 다")
    void blankAppRefIsNotFound() {
        for (String bad : new String[]{null, "", "   ", "app:", "app:   "}) {
            assertThatThrownBy(() -> resolver.resolveAppKey(bad))
                    .as("appRef=%s", bad)
                    .isInstanceOfSatisfying(BlockedException.class,
                            e -> assertThat(e.code).isEqualTo(ErrorCode.REF_NOT_FOUND));
        }
    }

    @Test
    @DisplayName("refOf 는 스냅샷에 있는 hwnd 만 ref 로 돌려준다")
    void refOfLooksUpSnapshot() {
        givenWindows();

        assertThat(resolver.refOf(200L)).isEqualTo("win:2");
        assertThat(resolver.refOf(999L)).isNull();
    }
}
