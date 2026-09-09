package com.sia.assistant.common;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Instant;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class TimesTest {

    @Test
    @DisplayName("epoch 는 UTC 'yyyy-MM-dd HH:mm:ss.SSS' 고정폭 23자로 포맷된다")
    void formatsEpochAsFixedWidthUtc() {
        assertThat(Times.of(Instant.EPOCH)).isEqualTo("1970-01-01 00:00:00.000");
    }

    @Test
    @DisplayName("now/ofEpochMs/daysAgo 모두 밀리초 포함 23자 고정폭이다")
    void allOutputsAreFixedWidth() {
        assertThat(Times.now()).hasSize(23);
        assertThat(Times.ofEpochMs(1_000L)).isEqualTo("1970-01-01 00:00:01.000");
        assertThat(Times.daysAgo(1)).hasSize(23);
    }

    @Test
    @DisplayName("parse 는 of 의 역함수다")
    void parseIsInverseOfFormat() {
        Instant instant = Instant.parse("2026-08-28T01:02:03.456Z");
        assertThat(Times.parse(Times.of(instant))).isEqualTo(instant);
    }

    @Test
    @DisplayName("고정폭이라 문자열 비교가 시간 비교와 일치한다")
    void lexicographicOrderMatchesChronologicalOrder() {
        assertThat(Times.ofEpochMs(1_000L)).isLessThan(Times.ofEpochMs(2_000L));
        // 밀리초 자리(…00.009)와 초 자리(…10.000)가 폭이 같아야 성립하는 비교
        assertThat(Times.ofEpochMs(9L)).isLessThan(Times.ofEpochMs(10_000L));
        assertThat(Times.daysAgo(3)).isLessThan(Times.now());
    }
}
