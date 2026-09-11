package com.sia.assistant.registration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyBoolean;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.Sha256;
import com.sia.assistant.config.DataDirs;
import com.sia.assistant.settings.GestureService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.ArgumentCaptor;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * 커스텀 제스처 등록 — 템플릿 npz 는 등록 중 PUT 으로 임시본에 들어오고, macro_assign 이 행으로 확정한다 (흐름도 03).
 * npz 없이 확정할 수 없고, 확정 통지 gesture_registered 는 id·sha256 을 싣는다.
 * 등록 창은 정적/동적으로 갈린다 — motion 은 reg_start 의 입력(FE), hands 는 reg_captured 의 관측값(AI)이다.
 */
class RegistrationOrchestratorTest {

    private final ObjectMapper om = new ObjectMapper();
    private AgentHub agentHub;
    private FeHub feHub;
    private GestureService gestureService;
    private WebmEncoder encoder;
    private Path previews;
    private Path gestures;
    private RegistrationOrchestrator orchestrator;

    @BeforeEach
    void setUp(@TempDir Path dir) throws Exception {
        agentHub = mock(AgentHub.class);
        feHub = mock(FeHub.class);
        gestureService = mock(GestureService.class);
        DataDirs dataDirs = new DataDirs(dir.toString());
        previews = Files.createDirectories(dataDirs.previews());
        gestures = Files.createDirectories(dataDirs.gestures());
        encoder = mock(WebmEncoder.class);
        orchestrator = new RegistrationOrchestrator(agentHub, feHub, gestureService, encoder,
                new PreviewStore(dataDirs), dataDirs, om);
    }

    /** reg_recorded 까지 끝난 상태 — 회차 3개가 previews/ 에 있다. */
    private void recorded(String tempId) throws Exception {
        for (int take = 1; take <= 3; take++) {
            Files.write(previews.resolve(tempId + "-" + take + ".webm"), new byte[]{1});
        }
    }

    private JsonNode assignBody(String tempId) throws Exception {
        return om.readTree("{\"tempId\":\"" + tempId + "\",\"take\":2,\"name\":\"손가락 하트\",\"label\":\"음악 재생\","
                + "\"steps\":[{\"tool\":\"media.play_pause\"}]}");
    }

    @Test
    @DisplayName("npz 는 진행 중인 등록의 tempId 로만 받고, 크기는 1B~5MB 다")
    void attachNpzGuards() {
        assertThatThrownBy(() -> orchestrator.attachNpz("nope", new byte[]{1}))
                .isInstanceOf(ApiException.class).hasMessageContaining("진행 중인 제스처 등록");

        String tempId = orchestrator.start(null, null);
        assertThatThrownBy(() -> orchestrator.attachNpz(tempId, new byte[0]))
                .isInstanceOf(ApiException.class).hasMessageContaining("5MB");
    }

    @Test
    @DisplayName("템플릿이 도착하지 않았으면 macro_assign 은 거절되고 아무것도 저장·통지되지 않는다")
    void assignRequiresNpz() throws Exception {
        String tempId = orchestrator.start(null, null);

        assertThatThrownBy(() -> orchestrator.assign(assignBody(tempId)))
                .isInstanceOf(ApiException.class).hasMessageContaining("템플릿");

        verify(gestureService, never()).saveCustom(any(), any(), any(), any(), anyBoolean(), any(), any(), any(), any(), any());
        verify(agentHub, never()).send(eq("gesture_registered"), any());
        verify(feHub, never()).send(eq("macro_saved"), any());
    }

    @Test
    @SuppressWarnings("unchecked")
    @DisplayName("신규 등록: PUT 된 npz 가 행에 저장되고 gesture_registered 에 id·sha256 이 실린다. 확정 후 상태는 해제된다")
    void assignStoresNpzAndNotifies() throws Exception {
        String tempId = orchestrator.start(null, null);
        byte[] npz = {1, 2, 3};
        orchestrator.attachNpz(tempId, npz);
        when(gestureService.saveCustom(eq("손가락 하트"), eq("음악 재생"), any(), any(), eq(false), any(),
                eq(npz), eq(Sha256.hex(npz)), any(), eq("DYNAMIC"))).thenReturn(14L);

        orchestrator.assign(assignBody(tempId));

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(agentHub).send(eq("gesture_registered"), captor.capture());
        assertThat(captor.getValue()).containsEntry("id", 14L).containsEntry("take", 2)
                .containsEntry("name", "손가락 하트").containsEntry("sha256", Sha256.hex(npz));
        verify(feHub).send(eq("macro_saved"), any());
        verify(agentHub, never()).send(eq("settings_changed"), any());

        // 사이클이 끝나 임시본이 없다 — 같은 tempId 로 다시 확정할 수 없다
        assertThatThrownBy(() -> orchestrator.assign(assignBody(tempId)))
                .isInstanceOf(ApiException.class).hasMessageContaining("진행 중인 제스처 등록");
    }

    @Test
    @SuppressWarnings("unchecked")
    @DisplayName("동작 재촬영(replaceGestureId): 기존 행의 템플릿을 교체하고 새 행을 만들지 않는다")
    void replaceUpdatesExistingTemplate() throws Exception {
        Map<String, Object> existing = new LinkedHashMap<>();
        existing.put("id", 7L);
        existing.put("name", "손가락 하트");
        when(gestureService.getOne(7L)).thenReturn(existing);
        String tempId = orchestrator.start(7L, null);
        byte[] npz = {9, 9};
        orchestrator.attachNpz(tempId, npz);

        orchestrator.assign(assignBody(tempId));

        verify(gestureService).update(eq(7L), eq("손가락 하트"), eq("음악 재생"), any(), eq(false), any());
        verify(gestureService).updateNpz(7L, npz, Sha256.hex(npz), null, "DYNAMIC");
        verify(gestureService, never()).saveCustom(any(), any(), any(), any(), anyBoolean(), any(), any(), any(), any(), any());
        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(agentHub).send(eq("gesture_registered"), captor.capture());
        assertThat(captor.getValue()).containsEntry("id", 7L).containsEntry("sha256", Sha256.hex(npz));
    }

    @Test
    @DisplayName("승격이 끝나면 고른 회차를 포함해 그 등록의 미리보기를 모두 지운다 — 다른 등록 것은 남는다")
    void assignClearsPreviewsOfThatRegistration() throws Exception {
        String tempId = orchestrator.start(null, null);
        orchestrator.attachNpz(tempId, new byte[]{1, 2, 3});
        recorded(tempId);
        Files.write(previews.resolve("other11-1.webm"), new byte[]{1});
        when(gestureService.saveCustom(any(), any(), any(), any(), anyBoolean(), any(), any(), any(), any(), any()))
                .thenReturn(14L);

        orchestrator.assign(assignBody(tempId)); // take=2

        assertThat(gestures.resolve("g14.webm")).exists();
        verify(gestureService).setVideoPath(14L, "g14.webm");
        assertThat(previews.toFile().list()).containsExactly("other11-1.webm");
    }

    @Test
    @DisplayName("거절되면 인코딩까지 끝난 촬영본도 남기지 않는다")
    void rejectClearsPreviews() throws Exception {
        String tempId = orchestrator.start(null, null);
        recorded(tempId);

        orchestrator.onRejected(tempId, om.readTree("{\"reason\":\"손이 화면을 벗어났습니다\"}"));

        assertThat(previews.toFile().list()).isEmpty();
    }

    @Test
    @DisplayName("등록을 새로 시작하면 버려지는 이전 등록의 미리보기도 함께 지운다")
    void restartClearsAbandonedPreviews() throws Exception {
        String abandoned = orchestrator.start(null, null);
        recorded(abandoned);

        orchestrator.start(null, null);

        assertThat(previews.toFile().list()).isEmpty();
    }

    @Test
    @SuppressWarnings("unchecked")
    @DisplayName("정적 등록은 reg_mode_start 에 motion 을 싣고 takeDurationSec 를 아예 보내지 않는다 — 구간이 없다")
    void staticModeStartOmitsTakeDuration() {
        orchestrator.start(null, "static");

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(agentHub).send(eq("reg_mode_start"), captor.capture());
        assertThat(captor.getValue()).containsEntry("motion", "STATIC").containsEntry("takes", 3)
                .containsEntry("countdownSec", 3)
                .doesNotContainKey("takeDurationSec");
    }

    @Test
    @SuppressWarnings("unchecked")
    @DisplayName("동적 등록은 촬영 구간(takeDurationSec)을 그대로 보낸다 — motion 을 안 주면 동적이다")
    void dynamicModeStartKeepsTakeDuration() {
        orchestrator.start(null, null);

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(agentHub).send(eq("reg_mode_start"), captor.capture());
        assertThat(captor.getValue()).containsEntry("motion", "DYNAMIC").containsEntry("takeDurationSec", 2);
    }

    @Test
    @SuppressWarnings("unchecked")
    @DisplayName("정적 등록은 회차별 프레임을 인코딩하지 않고 마지막 사진 한 장을 jpg 로 남긴다")
    void staticTakesAreSavedAsJpeg() {
        String tempId = orchestrator.start(null, "STATIC");
        byte[] first = {10};
        byte[] last = {20};
        orchestrator.onFrame(tempId, 1, 1, 100, Base64.getEncoder().encodeToString(first));
        orchestrator.onFrame(tempId, 1, 2, 200, Base64.getEncoder().encodeToString(last));

        orchestrator.stop(tempId);

        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(feHub, timeout(5000)).send(eq("reg_recorded"), captor.capture());
        List<Map<String, Object>> takes = (List<Map<String, Object>>) captor.getValue().get("takes");
        assertThat(takes).hasSize(1);
        assertThat(takes.get(0)).containsEntry("webmUrl", "/api/previews/" + tempId + "-1.jpg");
        // 자세가 가장 정착된 마지막 장이 남는다
        assertThat(previews.resolve(tempId + "-1.jpg")).hasBinaryContent(last);
        verifyNoInteractions(encoder);
    }

    @Test
    @DisplayName("정적 등록의 승격본은 g{id}.jpg 다 — 경로는 하나이고 확장자만 갈린다")
    void staticPromotesToJpeg() throws Exception {
        String tempId = orchestrator.start(null, "STATIC");
        orchestrator.attachNpz(tempId, new byte[]{1, 2, 3});
        for (int take = 1; take <= 3; take++) {
            Files.write(previews.resolve(tempId + "-" + take + ".jpg"), new byte[]{1});
        }
        when(gestureService.saveCustom(any(), any(), any(), any(), anyBoolean(), any(), any(), any(),
                any(), any())).thenReturn(14L);

        orchestrator.assign(assignBody(tempId)); // take=2

        assertThat(gestures.resolve("g14.jpg")).exists();
        verify(gestureService).setVideoPath(14L, "g14.jpg");
        assertThat(previews.toFile().list()).isEmpty();
    }

    @Test
    @DisplayName("reg_captured 의 hands 가 macro_assign 의 저장으로 그대로 넘어간다 — 없으면 NULL 로 저장된다")
    void capturedHandsReachesSave() throws Exception {
        String tempId = orchestrator.start(null, "STATIC");
        byte[] npz = {1, 2, 3};
        orchestrator.attachNpz(tempId, npz);
        orchestrator.onCaptured(tempId, om.readTree("{\"tempId\":\"" + tempId + "\",\"hands\":2}"));
        when(gestureService.saveCustom(any(), any(), any(), any(), anyBoolean(), any(), any(), any(),
                any(), any())).thenReturn(14L);

        orchestrator.assign(assignBody(tempId));

        verify(gestureService).saveCustom(eq("손가락 하트"), eq("음악 재생"), any(), any(), eq(false), any(),
                eq(npz), eq(Sha256.hex(npz)), eq(2), eq("STATIC"));
    }
}
