package com.sia.assistant.ws;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.Mockito.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.slf4j.LoggerFactory;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

class BaseHubTest {

    private final ObjectMapper om = new ObjectMapper();

    /** 콜백 호출을 기록만 하는 테스트용 허브. */
    private static class TestHub extends BaseHub {
        record Received(String type, JsonNode data) {
        }

        final List<Received> received = new ArrayList<>();
        int connects;
        int disconnects;

        TestHub(ObjectMapper om) {
            super(om);
        }

        @Override
        protected String name() {
            return "ws/test";
        }

        @Override
        protected void onMessage(String type, JsonNode data) {
            received.add(new Received(type, data));
        }

        @Override
        protected void onConnected() {
            connects++;
        }

        @Override
        protected void onDisconnected() {
            disconnects++;
        }
    }

    private TestHub hub;
    private WebSocketSession session;

    private final ch.qos.logback.classic.Logger hubLogger =
            (ch.qos.logback.classic.Logger) LoggerFactory.getLogger(BaseHub.class);
    private final ListAppender<ILoggingEvent> logs = new ListAppender<>();
    private Level previousLevel;

    @BeforeEach
    void setUp() {
        hub = new TestHub(om);
        session = mock(WebSocketSession.class);
        when(session.getId()).thenReturn("s1");
        previousLevel = hubLogger.getLevel();
        hubLogger.setLevel(Level.DEBUG);
        logs.start();
        hubLogger.addAppender(logs);
    }

    @AfterEach
    void tearDown() {
        hubLogger.detachAppender(logs);
        hubLogger.setLevel(previousLevel);
    }

    private List<String> messagesAt(Level level) {
        return logs.list.stream()
                .filter(e -> e.getLevel() == level)
                .map(ILoggingEvent::getFormattedMessage)
                .toList();
    }

    private JsonNode lastSentTo(WebSocketSession target) throws Exception {
        ArgumentCaptor<TextMessage> captor = ArgumentCaptor.forClass(TextMessage.class);
        verify(target).sendMessage(captor.capture());
        return om.readTree(captor.getValue().getPayload());
    }

    @Test
    @DisplayName("구독자가 없으면 send 는 조용한 no-op 이다")
    void sendWithoutSubscribersIsNoop() {
        assertThat(hub.connected()).isFalse();
        assertThatCode(() -> hub.send("evt", Map.of())).doesNotThrowAnyException();
    }

    @Test
    @DisplayName("연결되면 onConnected 가 불리고 {type, data} 봉투로 브로드캐스트된다")
    void sendWrapsInEnvelope() throws Exception {
        hub.afterConnectionEstablished(session);

        assertThat(hub.connected()).isTrue();
        assertThat(hub.connects).isEqualTo(1);

        hub.send("session_state", Map.of("state", "ACTIVE"));

        JsonNode envelope = lastSentTo(session);
        assertThat(envelope.path("type").asText()).isEqualTo("session_state");
        assertThat(envelope.path("data").path("state").asText()).isEqualTo("ACTIVE");
    }

    @Test
    @DisplayName("data 가 null 이면 빈 객체로 내려간다")
    void nullDataBecomesEmptyObject() throws Exception {
        hub.afterConnectionEstablished(session);

        hub.send("ping", null);

        assertThat(lastSentTo(session).path("data").isObject()).isTrue();
    }

    @Test
    @DisplayName("수신 메시지는 type·data 로 풀려 onMessage 에 전달된다")
    void inboundMessageIsDispatched() throws Exception {
        hub.afterConnectionEstablished(session);

        hub.handleTextMessage(session, new TextMessage("{\"type\":\"gesture\",\"data\":{\"x\":1}}"));

        assertThat(hub.received).hasSize(1);
        assertThat(hub.received.get(0).type()).isEqualTo("gesture");
        assertThat(hub.received.get(0).data().path("x").asInt()).isEqualTo(1);
    }

    @Test
    @DisplayName("type 없는 메시지는 처리 대신 error 봉투를 돌려받는다")
    void missingTypeGetsErrorReply() throws Exception {
        hub.afterConnectionEstablished(session);

        hub.handleTextMessage(session, new TextMessage("{\"data\":{}}"));

        assertThat(hub.received).isEmpty();
        assertThat(lastSentTo(session).path("type").asText()).isEqualTo("error");
    }

    @Test
    @DisplayName("JSON 이 아닌 페이로드도 error 봉투로 응답한다")
    void invalidJsonGetsErrorReply() throws Exception {
        hub.afterConnectionEstablished(session);

        hub.handleTextMessage(session, new TextMessage("not-json"));

        assertThat(hub.received).isEmpty();
        assertThat(lastSentTo(session).path("type").asText()).isEqualTo("error");
    }

    @Test
    @DisplayName("전송이 실패한 구독자는 즉시 제거된다")
    void failingSubscriberIsEvicted() throws Exception {
        hub.afterConnectionEstablished(session);
        doThrow(new RuntimeException("송신 실패")).when(session).sendMessage(any());

        assertThatCode(() -> hub.send("evt", Map.of())).doesNotThrowAnyException();

        assertThat(hub.connected()).isFalse();
    }

    @Test
    @DisplayName("송신·수신 한 건마다 방향·type·페이로드가 INFO 한 줄로 남는다")
    void trafficIsLoggedAtInfo() {
        hub.afterConnectionEstablished(session);

        hub.handleTextMessage(session, new TextMessage("{\"type\":\"calib_start\",\"data\":{\"n\":1}}"));
        hub.send("session_state", Map.of("state", "ACTIVE"));

        assertThat(messagesAt(Level.INFO))
                .anySatisfy(m -> assertThat(m).isEqualTo("[ws/test] <- calib_start {\"n\":1}"))
                .anySatisfy(m -> assertThat(m).isEqualTo("[ws/test] -> session_state {\"state\":\"ACTIVE\"}"));
    }

    @Test
    @DisplayName("gaze_cursor·reg_frame 같은 고빈도 type 은 INFO 가 아니라 DEBUG 로 내려간다")
    void noisyTypesAreDebug() {
        hub.afterConnectionEstablished(session);

        hub.handleTextMessage(session, new TextMessage("{\"type\":\"gaze_cursor\",\"data\":{\"x\":3}}"));
        hub.send("reg_frame", Map.of("seq", 7));

        assertThat(messagesAt(Level.INFO)).noneMatch(m -> m.contains("gaze_cursor") || m.contains("reg_frame"));
        assertThat(messagesAt(Level.DEBUG))
                .anyMatch(m -> m.startsWith("[ws/test] <- gaze_cursor"))
                .anyMatch(m -> m.startsWith("[ws/test] -> reg_frame"));
    }

    @Test
    @DisplayName("긴 페이로드는 300자에서 잘리고 원본 길이가 붙는다")
    void longPayloadIsTruncated() {
        String big = "x".repeat(1000);
        String preview = BaseHub.preview(big);

        assertThat(preview).startsWith("x".repeat(300)).endsWith("…(1000자)");
        assertThat(BaseHub.preview("short")).isEqualTo("short");
        assertThat(BaseHub.preview(null)).isEqualTo("{}");
    }

    @Test
    @DisplayName("연결이 닫히면 구독자에서 빠지고 onDisconnected 가 불린다")
    void closedSessionIsRemoved() {
        hub.afterConnectionEstablished(session);

        hub.afterConnectionClosed(session, CloseStatus.NORMAL);

        assertThat(hub.connected()).isFalse();
        assertThat(hub.disconnects).isEqualTo(1);
    }
}
