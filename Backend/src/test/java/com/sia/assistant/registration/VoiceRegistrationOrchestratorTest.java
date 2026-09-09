package com.sia.assistant.registration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.profile.VoiceProfileService;
import com.sia.assistant.settings.SettingsService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import tools.jackson.databind.ObjectMapper;

/**
 * 보이스 등록 — 5문장 핸드셰이크, 문장 재시도, 커밋 전 임시본, 한도(4개) 거절 (와이어프레임 보이스 섹션).
 */
class VoiceRegistrationOrchestratorTest {

    private final ObjectMapper om = new ObjectMapper();
    private AgentHub agentHub;
    private FeHub feHub;
    private VoiceProfileService voiceProfiles;
    private SettingsService settingsService;
    private VoiceRegistrationOrchestrator orchestrator;

    @BeforeEach
    void setUp() {
        agentHub = mock(AgentHub.class);
        feHub = mock(FeHub.class);
        voiceProfiles = mock(VoiceProfileService.class);
        settingsService = mock(SettingsService.class);
        orchestrator = new VoiceRegistrationOrchestrator(agentHub, feHub, voiceProfiles, settingsService);
    }

    @SuppressWarnings("unchecked")
    private String startAndGetTempId() {
        when(voiceProfiles.count()).thenReturn(0);
        orchestrator.start();
        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(agentHub).send(eq("voice_reg_start"), captor.capture());
        assertThat(captor.getValue()).containsEntry("total", 5);
        return (String) captor.getValue().get("tempId");
    }

    @Test
    @DisplayName("문장은 5개 — ready 에 1번, progress n 에 n+1 번 문장이 FE·AI 양쪽으로 나간다")
    void fiveSentenceHandshake() {
        String tempId = startAndGetTempId();

        orchestrator.onReady(tempId);
        verify(feHub).send(eq("voice_sentence"), argThatMap("n", 1));
        verify(agentHub).send(eq("voice_collect"), argThatMap("n", 1));

        orchestrator.onProgress(tempId, 1);
        verify(feHub).send(eq("voice_progress"), argThatMap("n", 1));
        verify(feHub).send(eq("voice_sentence"), argThatMap("n", 2));

        orchestrator.onProgress(tempId, 5); // 마지막 문장 — 다음 문장 없음
        verify(feHub, never()).send(eq("voice_sentence"), argThatMap("n", 6));
    }

    @Test
    @DisplayName("'이 문장 다시'는 같은 번호의 voice_collect 를 재발급한다")
    void sentenceRetryReissuesSameNumber() {
        String tempId = startAndGetTempId();
        orchestrator.onReady(tempId);
        orchestrator.onProgress(tempId, 1); // 현재 2번 문장

        orchestrator.retrySentence(tempId);

        verify(agentHub, org.mockito.Mockito.times(2)).send(eq("voice_collect"), argThatMap("n", 2));
    }

    @Test
    @DisplayName("커밋은 npz 가 도착해 있어야 하고, 마이크 이름을 프로필에 찍는다")
    void commitRequiresNpzAndStampsMic() {
        String tempId = startAndGetTempId();
        assertThatThrownBy(() -> orchestrator.commit(tempId, null, null))
                .isInstanceOf(ApiException.class);

        orchestrator.attachNpz(tempId, new byte[]{1});
        orchestrator.attachSample(tempId, new byte[]{2}, "audio/webm");
        when(settingsService.peekString("micDevice")).thenReturn("Realtek Audio");
        when(voiceProfiles.saveNew(any(), any(), anyString(), any(), anyString(),
                any(), any(), any(), anyString())).thenReturn(3L);
        when(voiceProfiles.activeIdOrNull()).thenReturn(3L);
        when(voiceProfiles.list()).thenReturn(List.of(Map.of("id", 3L, "name", "내 목소리 1")));

        orchestrator.commit(tempId, null, null);

        verify(voiceProfiles).saveNew(eq(null), any(), anyString(), any(), eq("audio/webm"),
                any(), any(), any(), eq("Realtek Audio"));
        verify(feHub).send(eq("voice_saved"), any());
        verify(agentHub).send(eq("voice_registered"), any());
    }

    @Test
    @DisplayName("FE 가 보낸 deviceLabel(실제 사용한 OS 장치 이름)이 설정값을 이긴다 — 시스템 기본일 때의 실명 경로")
    void feDeviceLabelWinsOverSetting() {
        String tempId = startAndGetTempId();
        orchestrator.attachNpz(tempId, new byte[]{1});
        orchestrator.attachSample(tempId, new byte[]{2}, "audio/webm");
        when(settingsService.peekString("micDevice")).thenReturn(null); // 설정은 "시스템 기본"
        when(voiceProfiles.saveNew(any(), any(), anyString(), any(), anyString(),
                any(), any(), any(), anyString())).thenReturn(3L);
        when(voiceProfiles.list()).thenReturn(List.of(Map.of("id", 3L, "name", "내 목소리 1")));

        orchestrator.commit(tempId, null, "  마이크(Realtek(R) Audio)  ");

        verify(voiceProfiles).saveNew(eq(null), any(), anyString(), any(), eq("audio/webm"),
                any(), any(), any(), eq("마이크(Realtek(R) Audio)"));
    }

    @Test
    @DisplayName("프로필이 4개 차 있으면 시작하지 않고 voice_reg_denied 를 회신한다")
    void deniedWhenFull() {
        when(voiceProfiles.count()).thenReturn(VoiceProfileService.MAX_PROFILES);
        orchestrator.start();
        verify(feHub).send(eq("voice_reg_denied"), any());
        verify(agentHub, never()).send(eq("voice_reg_start"), any());
    }

    @Test
    @DisplayName("음질 경고 후 '그대로 진행'은 AI 에 voice_finalize 를 보낸다")
    void acceptAnywayFinalizes() throws Exception {
        String tempId = startAndGetTempId();
        orchestrator.onQualityWarn(tempId, om.readTree("{\"reason\":\"소음\",\"noise\":\"높음\"}"));
        verify(feHub).send(eq("voice_quality_warn"), any());

        orchestrator.acceptAnyway(tempId);
        verify(agentHub).send(eq("voice_finalize"), any());
    }

    /** 페이로드 맵에서 키 하나만 보는 매처 — BaseHub.send(String, Object) 의 두 번째 인자용. */
    private static Object argThatMap(String key, Object value) {
        return org.mockito.ArgumentMatchers.argThat(m ->
                m instanceof Map<?, ?> map && value.equals(map.get(key)));
    }
}
