package com.sia.assistant.common;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class LogPreviewTest {

    @Test
    @DisplayName("300자를 넘으면 앞 300자만 남기고 원본 길이를 붙인다")
    void truncatesWithOriginalLength() {
        assertThat(LogPreview.of("x".repeat(1000))).startsWith("x".repeat(300)).endsWith("…(1000자)");
        assertThat(LogPreview.of("x".repeat(300))).hasSize(300);
    }

    @Test
    @DisplayName("짧은 값은 그대로, null 은 빈 객체 표기다")
    void shortAndNullPassThrough() {
        assertThat(LogPreview.of("short")).isEqualTo("short");
        assertThat(LogPreview.of(null)).isEqualTo("{}");
    }

    @Test
    @DisplayName("절단 지점이 서로게이트 쌍 중간이면 한 글자 앞에서 자른다")
    void doesNotSplitSurrogatePair() {
        String s = "a".repeat(299) + "😀" + "b".repeat(50);
        String preview = LogPreview.of(s);
        assertThat(preview).startsWith("a".repeat(299) + "…");
    }
}
