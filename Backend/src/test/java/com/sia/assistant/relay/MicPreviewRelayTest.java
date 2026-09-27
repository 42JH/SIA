package com.sia.assistant.relay;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import com.sia.assistant.ws.WsEvents;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import tools.jackson.databind.ObjectMapper;

/**
 * 마이크 입력 레벨 중계 — AI 가 이미 연 마이크의 진폭을 FE 로 흘려 파형을 그리게 한다 (프로토콜 §5.5).
 * 카메라 미리보기와 수명 규칙이 같지만 <b>등록이 시작돼도 끊지 않는다</b>는 점이 다르다 —
 * 말하는 동안 파형이 움직여야 하는 게 목적이라 거기가 바로 켜져 있어야 할 구간이다.
 */
class MicPreviewRelayTest {

    private final ObjectMapper om = new ObjectMapper();
    private AgentHub agentHub;
    private FeHub feHub;
    private MicPreviewRelay relay;

    @BeforeEach
    void setUp() {
        agentHub = mock(AgentHub.class);
        feHub = mock(FeHub.class);
        when(agentHub.connected()).thenReturn(true);
        relay = new MicPreviewRelay(agentHub, feHub);
    }

    private String level(long seq, String level) {
        return "{\"seq\":" + seq + ",\"tsMs\":1788148327913,\"level\":" + level + "}";
    }

    @Test
    @DisplayName("AI 가 연결돼 있지 않으면 start 가 거부된다 — 켜 봐야 레벨이 하나도 안 온다")
    void startRequiresAgent() {
        when(agentHub.connected()).thenReturn(false);

        assertThatThrownBy(() -> relay.start())
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("AI");
        verify(agentHub, never()).send(eq("mic_preview_start"), any());
    }

    @Test
    @DisplayName("이미 켜져 있으면 AI 에 중복 start 를 보내지 않는다")
    void duplicateStartIsNotRelayed() {
        relay.start();
        relay.start();

        verify(agentHub).send(eq("mic_preview_start"), any());
    }

    @SuppressWarnings("unchecked")
    @Test
    @DisplayName("꺼진 미리보기의 레벨은 FE 로 가지 않는다 — stop 이후 늦게 온 것을 버린다")
    void levelsAreDroppedWhilePreviewIsOff() throws Exception {
        relay.onLevel(om.readTree(level(1, "0.4"))); // 아직 start 전

        relay.start();
        relay.onLevel(om.readTree(level(2, "0.4")));
        relay.stop();
        relay.onLevel(om.readTree(level(3, "0.4"))); // stop 이후 늦게 도착

        ArgumentCaptor<Object> captor = ArgumentCaptor.forClass(Object.class);
        verify(feHub).send(eq("mic_preview_level"), captor.capture());
        Map<String, Object> body = (Map<String, Object>) captor.getValue();
        // 켜져 있던 동안의 seq=2 하나만 나간다
        assertThat(body).containsEntry("seq", 2L);
        // tsMs 는 BE 가 쓰지 않으므로 떼고 보낸다
        assertThat(body).containsOnlyKeys("seq", "level");
    }

    @Test
    @DisplayName("level 이 없거나 숫자가 아니면 버린다 — 0 으로 읽으면 무음과 구분이 안 된다")
    void nonNumericLevelIsDropped() throws Exception {
        relay.start();

        relay.onLevel(om.readTree("{\"seq\":1}"));
        relay.onLevel(om.readTree("{\"seq\":2,\"level\":null}"));
        relay.onLevel(om.readTree(level(3, "\"0.4\"")));

        verify(feHub, never()).send(eq("mic_preview_level"), any());
    }

    @SuppressWarnings("unchecked")
    @Test
    @DisplayName("범위를 벗어난 레벨은 버리지 않고 0~1 로 자른다 — 포화에 막대가 빠지면 파형이 끊겨 보인다")
    void outOfRangeLevelIsClamped() throws Exception {
        relay.start();

        relay.onLevel(om.readTree(level(1, "1.4")));
        relay.onLevel(om.readTree(level(2, "-0.2")));

        ArgumentCaptor<Object> captor = ArgumentCaptor.forClass(Object.class);
        verify(feHub, org.mockito.Mockito.times(2)).send(eq("mic_preview_level"), captor.capture());
        assertThat((Map<String, Object>) captor.getAllValues().get(0)).containsEntry("level", 1.0);
        assertThat((Map<String, Object>) captor.getAllValues().get(1)).containsEntry("level", 0.0);
    }

    @Test
    @DisplayName("state 는 상태와 무관하게 중계된다 — STOPPED 는 이미 꺼진 뒤에 온다")
    void stateIsRelayedEvenWhenOff() throws Exception {
        relay.onState(om.readTree("{\"phase\":\"STOPPED\"}"));

        verify(feHub).send(eq("mic_preview_state"), any());
    }

    @Test
    @DisplayName("마지막 FE 구독자가 나가면 AI 송출을 끊는다 — 안 그러면 아무도 안 보는 레벨을 계속 만든다")
    void lastFeLeavingStopsPreview() {
        relay.start();
        clearInvocations(agentHub);
        when(feHub.connected()).thenReturn(false);

        relay.onFeDisconnected(new WsEvents.FeDisconnected());

        verify(agentHub).send(eq("mic_preview_stop"), any());
    }

    @Test
    @DisplayName("탭이 하나 닫혀도 다른 탭이 남아 있으면 계속 보낸다")
    void otherFeTabKeepsPreviewAlive() {
        relay.start();
        clearInvocations(agentHub);
        when(feHub.connected()).thenReturn(true);

        relay.onFeDisconnected(new WsEvents.FeDisconnected());

        verify(agentHub, never()).send(eq("mic_preview_stop"), any());
    }

    @Test
    @DisplayName("AI 가 나가면 stop 을 보내지 않고 상태만 내린다 — 보낼 곳이 없다")
    void agentLeavingOnlyClearsState() throws Exception {
        relay.start();
        clearInvocations(agentHub);

        relay.onAgentDisconnected(new WsEvents.AgentDisconnected());

        verify(agentHub, never()).send(eq("mic_preview_stop"), any());
        // 상태가 내려갔으므로 뒤늦은 레벨도 버린다
        relay.onLevel(om.readTree(level(9, "0.4")));
        verify(feHub, never()).send(eq("mic_preview_level"), any());
    }
}
