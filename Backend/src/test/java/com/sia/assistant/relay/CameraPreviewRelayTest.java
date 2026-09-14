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
import java.util.Base64;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import tools.jackson.databind.ObjectMapper;

/**
 * 촬영 전 카메라 미리보기 중계 — AI 가 이미 연 카메라의 프레임을 FE 로 흘린다 (PROTOCOL.md §5·§6).
 * 수명 관리는 전부 BE 몫이라 여기가 실제 난이도다: FE 가 stop 없이 사라지는 경우와
 * 실제 촬영이 시작되는 경우에 AI 송출을 끊어야 한다.
 */
class CameraPreviewRelayTest {

    private final ObjectMapper om = new ObjectMapper();
    private AgentHub agentHub;
    private FeHub feHub;
    private CameraPreviewRelay relay;

    @BeforeEach
    void setUp() {
        agentHub = mock(AgentHub.class);
        feHub = mock(FeHub.class);
        when(agentHub.connected()).thenReturn(true);
        relay = new CameraPreviewRelay(agentHub, feHub);
    }

    private String frame(long seq) {
        return "{\"seq\":" + seq + ",\"tsMs\":1788148327913,\"jpegB64\":\""
                + Base64.getEncoder().encodeToString(new byte[]{1, 2, 3}) + "\"}";
    }

    @Test
    @DisplayName("AI 가 연결돼 있지 않으면 start 가 거부된다 — 켜 봐야 프레임이 한 장도 안 온다")
    void startRequiresAgent() {
        when(agentHub.connected()).thenReturn(false);

        assertThatThrownBy(() -> relay.start())
                .isInstanceOf(ApiException.class)
                .hasMessageContaining("AI");
        verify(agentHub, never()).send(eq("cam_preview_start"), any());
    }

    @Test
    @DisplayName("이미 켜져 있으면 AI 에 중복 start 를 보내지 않는다")
    void duplicateStartIsNotRelayed() {
        relay.start();
        relay.start();

        verify(agentHub).send(eq("cam_preview_start"), any());
    }

    @SuppressWarnings("unchecked")
    @Test
    @DisplayName("꺼진 미리보기의 프레임은 FE 로 가지 않는다 — stop 이후 늦게 온 것을 버린다")
    void framesAreDroppedWhilePreviewIsOff() throws Exception {
        relay.onFrame(om.readTree(frame(1))); // 아직 start 전

        relay.start();
        relay.onFrame(om.readTree(frame(2)));
        relay.stop();
        relay.onFrame(om.readTree(frame(3))); // stop 이후 늦게 도착

        ArgumentCaptor<Object> captor = ArgumentCaptor.forClass(Object.class);
        verify(feHub).send(eq("cam_preview_frame"), captor.capture());
        assertThat(captor.getValue()).isInstanceOf(Map.class);
        Map<String, Object> body = (Map<String, Object>) captor.getValue();
        // 켜져 있던 동안의 seq=2 한 장만 나간다
        assertThat(body).containsEntry("seq", 2L);
        // tsMs 는 BE 가 쓰지 않으므로 떼고 보낸다
        assertThat(body).containsOnlyKeys("seq", "jpegB64");
    }

    @Test
    @DisplayName("state 는 상태와 무관하게 중계된다 — STOPPED 는 이미 꺼진 뒤에 온다")
    void stateIsRelayedEvenWhenOff() throws Exception {
        relay.onState(om.readTree("{\"phase\":\"STOPPED\"}"));

        verify(feHub).send(eq("cam_preview_state"), any());
    }

    @Test
    @DisplayName("마지막 FE 구독자가 나가면 AI 송출을 끊는다 — 안 그러면 아무도 안 보는 프레임을 계속 만든다")
    void lastFeLeavingStopsPreview() {
        relay.start();
        clearInvocations(agentHub);
        when(feHub.connected()).thenReturn(false);

        relay.onFeDisconnected(new WsEvents.FeDisconnected());

        verify(agentHub).send(eq("cam_preview_stop"), any());
    }

    @Test
    @DisplayName("탭이 하나 닫혀도 다른 탭이 남아 있으면 계속 보낸다")
    void otherFeTabKeepsPreviewAlive() {
        relay.start();
        clearInvocations(agentHub);
        when(feHub.connected()).thenReturn(true);

        relay.onFeDisconnected(new WsEvents.FeDisconnected());

        verify(agentHub, never()).send(eq("cam_preview_stop"), any());
    }

    @Test
    @DisplayName("AI 가 나가면 stop 을 보내지 않고 상태만 내린다 — 보낼 곳이 없다")
    void agentLeavingOnlyClearsState() throws Exception {
        relay.start();
        clearInvocations(agentHub);

        relay.onAgentDisconnected(new WsEvents.AgentDisconnected());

        verify(agentHub, never()).send(eq("cam_preview_stop"), any());
        // 상태가 내려갔으므로 뒤늦은 프레임도 버린다
        relay.onFrame(om.readTree(frame(9)));
        verify(feHub, never()).send(eq("cam_preview_frame"), any());
    }
}
