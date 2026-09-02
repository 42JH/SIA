package com.sia.assistant.ws;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.mockito.Mockito.any;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

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

    @BeforeEach
    void setUp() {
        hub = new TestHub(om);
        session = mock(WebSocketSession.class);
        when(session.getId()).thenReturn("s1");
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
    @DisplayName("연결이 닫히면 구독자에서 빠지고 onDisconnected 가 불린다")
    void closedSessionIsRemoved() {
        hub.afterConnectionEstablished(session);

        hub.afterConnectionClosed(session, CloseStatus.NORMAL);

        assertThat(hub.connected()).isFalse();
        assertThat(hub.disconnects).isEqualTo(1);
    }
}
