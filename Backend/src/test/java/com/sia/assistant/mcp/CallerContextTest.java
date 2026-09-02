package com.sia.assistant.mcp;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

class CallerContextTest {

    @AfterEach
    void tearDown() {
        CallerContext.clear();
    }

    @Test
    @DisplayName("아무것도 설정하지 않으면 LLM 이 기본값이다")
    void defaultsToLlm() {
        assertThat(CallerContext.get()).isEqualTo(Caller.LLM);
    }

    @Test
    @DisplayName("set 한 값은 같은 스레드에서 get 으로 돌아온다")
    void setAndGet() {
        CallerContext.set(Caller.GESTURE);
        assertThat(CallerContext.get()).isEqualTo(Caller.GESTURE);
    }

    @Test
    @DisplayName("clear 하면 기본값 LLM 으로 돌아간다")
    void clearRestoresDefault() {
        CallerContext.set(Caller.UI);
        CallerContext.clear();
        assertThat(CallerContext.get()).isEqualTo(Caller.LLM);
    }
}
