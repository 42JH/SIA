package com.sia.assistant.config;

import static org.assertj.core.api.Assertions.assertThat;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import jakarta.servlet.FilterChain;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.slf4j.LoggerFactory;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

class HttpLogFilterTest {

    private final HttpLogFilter filter = new HttpLogFilter();
    private final Logger logger = (Logger) LoggerFactory.getLogger(HttpLogFilter.class);
    private final ListAppender<ILoggingEvent> captured = new ListAppender<>();
    private Level previous;

    @BeforeEach
    void setUp() {
        previous = logger.getLevel();
        logger.setLevel(Level.DEBUG);
        captured.start();
        logger.addAppender(captured);
    }

    @AfterEach
    void tearDown() {
        logger.detachAppender(captured);
        logger.setLevel(previous);
    }

    private ILoggingEvent only() {
        assertThat(captured.list).hasSize(1);
        return captured.list.get(0);
    }

    @Test
    @DisplayName("/api 요청은 체인을 통과한 뒤 메서드·경로·쿼리·상태를 INFO 한 줄로 남긴다")
    void apiRequestIsLoggedAtInfo() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/api/tool-calls");
        request.setQueryString("page=2");
        MockHttpServletResponse response = new MockHttpServletResponse();
        AtomicBoolean reached = new AtomicBoolean();
        FilterChain chain = (req, res) -> {
            reached.set(true);
            ((MockHttpServletResponse) res).setStatus(204);
        };

        filter.doFilter(request, response, chain);

        assertThat(reached).isTrue();
        ILoggingEvent event = only();
        assertThat(event.getLevel()).isEqualTo(Level.INFO);
        assertThat(event.getFormattedMessage())
                .startsWith("[http] GET /api/tool-calls?page=2 -> 204 (")
                .endsWith("ms)");
    }

    @Test
    @DisplayName("/mcp 요청은 X-Caller 를 함께 적고, 헤더가 없으면 LLM 으로 표기한다")
    void mcpRequestShowsCaller() throws Exception {
        MockHttpServletRequest withHeader = new MockHttpServletRequest("POST", "/mcp");
        withHeader.addHeader("X-Caller", "GESTURE");
        filter.doFilter(withHeader, new MockHttpServletResponse(), (req, res) -> {
        });
        assertThat(only().getFormattedMessage()).contains("POST /mcp caller=GESTURE -> 200");

        captured.list.clear();
        filter.doFilter(new MockHttpServletRequest("POST", "/mcp"), new MockHttpServletResponse(),
                (req, res) -> {
                });
        assertThat(only().getFormattedMessage()).contains("caller=LLM");
    }

    @Test
    @DisplayName("체인이 예외로 끝나도 한 줄은 남고 예외는 그대로 위로 던져진다")
    void failureStillLogsAndRethrows() {
        MockHttpServletRequest request = new MockHttpServletRequest("DELETE", "/api/data");
        FilterChain chain = (req, res) -> {
            throw new IllegalStateException("boom");
        };

        org.assertj.core.api.Assertions.assertThatThrownBy(
                        () -> filter.doFilter(request, new MockHttpServletResponse(), chain))
                .isInstanceOf(IllegalStateException.class);

        assertThat(only().getFormattedMessage()).startsWith("[http] DELETE /api/data -> 200");
    }

    @Test
    @DisplayName("OPTIONS 프리플라이트와 /api·/mcp 밖의 경로는 DEBUG 로 내려간다")
    void preflightAndOtherPathsAreDebug() throws Exception {
        filter.doFilter(new MockHttpServletRequest("OPTIONS", "/api/settings"),
                new MockHttpServletResponse(), (req, res) -> {
                });
        filter.doFilter(new MockHttpServletRequest("GET", "/swagger-ui/index.html"),
                new MockHttpServletResponse(), (req, res) -> {
                });

        assertThat(captured.list).hasSize(2)
                .allSatisfy(e -> assertThat(e.getLevel()).isEqualTo(Level.DEBUG));
    }
}
