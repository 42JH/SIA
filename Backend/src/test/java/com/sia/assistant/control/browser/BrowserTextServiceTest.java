package com.sia.assistant.control.browser;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 접근성 폴백의 순수 부분 — 창 선택과 UIA 호출은 실 브라우저가 있어야 하므로
 * BrowserTextServiceLiveTest 가 맡고, 여기서는 판정과 정리 규칙만 본다.
 */
class BrowserTextServiceTest {

    @Test
    @DisplayName("브라우저 판정은 실행 파일명 기준이고 대소문자를 가리지 않는다")
    void browserDetection() {
        assertThat(BrowserTextService.isBrowser("chrome")).isTrue();
        assertThat(BrowserTextService.isBrowser("msedge")).isTrue();
        assertThat(BrowserTextService.isBrowser("MSEDGE")).isTrue();
        assertThat(BrowserTextService.isBrowser("firefox")).isTrue();

        assertThat(BrowserTextService.isBrowser("explorer")).isFalse();
        assertThat(BrowserTextService.isBrowser("notepad")).isFalse();
        // WindowService 가 프로세스를 못 열면 주는 값
        assertThat(BrowserTextService.isBrowser("unknown")).isFalse();
        assertThat(BrowserTextService.isBrowser(null)).isFalse();
    }

    @Test
    @DisplayName("접근성 텍스트 정리는 확장의 innerText 정리와 같은 규칙이다")
    void normalizeMatchesExtensionRules() {
        assertThat(BrowserTextService.normalize("  앞뒤   공백  ")).isEqualTo("앞뒤 공백");
        assertThat(BrowserTextService.normalize("줄1\n\n\n\n줄2")).isEqualTo("줄1\n\n줄2");
        assertThat(BrowserTextService.normalize("탭\t\t사이")).isEqualTo("탭 사이");
        // 접근성 트리는 CRLF 를 섞어 주기도 한다
        assertThat(BrowserTextService.normalize("줄1\r\n줄2")).isEqualTo("줄1\n줄2");
        // 줄 끝 공백이 남으면 LLM 토큰만 먹는다
        assertThat(BrowserTextService.normalize("줄1   \n   줄2")).isEqualTo("줄1\n줄2");
        assertThat(BrowserTextService.normalize(null)).isEmpty();
        assertThat(BrowserTextService.normalize("   ")).isEmpty();
    }

    @Test
    @DisplayName("Read 는 page 와 reason 중 하나만 채워진다")
    void readIsEitherOr() {
        BrowserTextService.Read ok =
                new BrowserTextService.Read(new BrowserTextService.Page(null, "제목", "본문", false), null);
        assertThat(ok.ok()).isTrue();

        BrowserTextService.Read fail = new BrowserTextService.Read(null, "열려 있는 브라우저 창을 찾지 못했습니다");
        assertThat(fail.ok()).isFalse();
        assertThat(fail.reason()).isNotBlank();
    }
}
