package com.sia.assistant.control.browser;

import static org.assertj.core.api.Assertions.assertThat;

import com.sia.assistant.control.com.ComWorker;
import com.sia.assistant.control.window.WindowService;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;

/**
 * 실제 브라우저 창을 대상으로 도는 스모크 테스트 — UIA vtable 인덱스가 맞는지는 이것으로만 확인된다
 * (컴파일은 vtable 번호가 틀려도 통과한다).
 *
 * <p>브라우저가 떠 있어야 하고 사용자 세션이 필요해 CI 에서는 돌 수 없다. 기본은 비활성이고
 * {@code ./gradlew test -Dsia.live.uia=true --tests '*BrowserTextServiceLiveTest'} 로만 켠다.
 * 본문 내용은 단언하지도 출력하지도 않는다 — 사용자가 보던 페이지이기 때문이다.
 */
@EnabledIfSystemProperty(named = "sia.live.uia", matches = "true")
class BrowserTextServiceLiveTest {

    @Test
    @DisplayName("떠 있는 브라우저 창에서 접근성으로 본문을 읽는다")
    void readsFromLiveBrowser() {
        ComWorker comWorker = new ComWorker();
        BrowserTextService service = new BrowserTextService(new WindowService(), comWorker);

        long t0 = System.currentTimeMillis();
        BrowserTextService.Read read = service.read();
        long elapsed = System.currentTimeMillis() - t0;

        System.out.printf("ok=%s reason=%s elapsed=%dms%n", read.ok(), read.reason(), elapsed);
        if (read.ok()) {
            BrowserTextService.Page page = read.page();
            System.out.printf("  url=%s%n  title.len=%d%n  text.len=%d truncated=%s%n",
                    page.url(), page.title() == null ? 0 : page.title().length(),
                    page.text().length(), page.truncated());
        }

        assertThat(read.ok())
                .withFailMessage("브라우저 창을 띄운 뒤 다시 실행하세요 — reason=%s", read.reason())
                .isTrue();
        assertThat(read.page().text()).isNotBlank();
        // dom_text 의 4초 예산 안에 들어와야 한다
        assertThat(elapsed).isLessThan(4000L);
    }
}
