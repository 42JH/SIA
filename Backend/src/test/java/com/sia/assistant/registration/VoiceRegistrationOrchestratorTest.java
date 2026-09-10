package com.sia.assistant.registration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.argThat;
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
 * 보이스 등록 — 5문장 핸드셰이크(진행은 사용자 확인이 방아쇠), 문장 재시도, 커밋 전 임시본,
 * 한도(4개) 거절 (와이어프레임 보이스 섹션).
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
    @DisplayName("통과만으로는 다음 문장이 나가지 않는다 — 사용자 확인에서 FE·AI 양쪽으로 나간다")
    void fiveSentenceHandshake() {
        String tempId = startAndGetTempId();

        orchestrator.onReady(tempId);
        verify(feHub).send(eq("voice_sentence"), argThatMap("n", 1));
        verify(agentHub).send(eq("voice_collect"), argThatMap("n", 1));

        orchestrator.onProgress(tempId, 1);
        verify(feHub).send(eq("voice_progress"), argThatMap("n", 1));
        verify(feHub, never()).send(eq("voice_sentence"), argThatMap("n", 2)); // 판독 결과 확인이 먼저다
        verify(agentHub, never()).send(eq("voice_collect"), argThatMap("n", 2)); // AI 도 아직 수집하지 않는다

        orchestrator.nextSentence(tempId);
        verify(feHub).send(eq("voice_sentence"), argThatMap("n", 2));
        verify(agentHub).send(eq("voice_collect"), argThatMap("n", 2));
    }

    @Test
    @DisplayName("마지막 문장에서 '다음'은 발급할 문장이 없다 — AI 의 voice_captured 가 녹음 확인으로 넘긴다")
    void lastSentenceHasNoNext() {
        String tempId = startAndGetTempId();
        orchestrator.onReady(tempId);
        for (int n = 1; n < 5; n++) {
            orchestrator.onProgress(tempId, n);
            orchestrator.nextSentence(tempId);
        }
        verify(feHub).send(eq("voice_sentence"), argThatMap("n", 5));

        orchestrator.onProgress(tempId, 5);
        orchestrator.nextSentence(tempId);

        verify(feHub, never()).send(eq("voice_sentence"), argThatMap("n", 6));
        verify(agentHub, never()).send(eq("voice_collect"), argThatMap("n", 6));
    }

    @Test
    @DisplayName("통과하지 않은 문장에서 '다음'은 무시한다 — 거절 뒤·연타로 문장을 건너뛰지 못한다")
    void nextIsIgnoredUntilSentencePasses() {
        String tempId = startAndGetTempId();
        orchestrator.onReady(tempId);

        orchestrator.nextSentence(tempId); // 아직 읽지도 않았다
        orchestrator.onSentenceRejected(tempId, om.readTree("{\"n\":1,\"reason\":\"너무 짧게 들렸어요.\"}"));
        orchestrator.nextSentence(tempId); // 거절된 문장
        verify(feHub, never()).send(eq("voice_sentence"), argThatMap("n", 2));

        orchestrator.onProgress(tempId, 1);
        orchestrator.nextSentence(tempId);
        orchestrator.nextSentence(tempId); // 연타

        verify(feHub, org.mockito.Mockito.times(1)).send(eq("voice_sentence"), argThatMap("n", 2));
        verify(feHub, never()).send(eq("voice_sentence"), argThatMap("n", 3));
    }

    @Test
    @DisplayName("voice_sentence·voice_progress 에는 AI 에 발급한 것과 같은 tempId 가 실린다 — FE 가 재시도·취소에 되돌려 보낸다")
    void sentenceAndProgressCarryTempId() {
        String tempId = startAndGetTempId();

        orchestrator.onReady(tempId);
        verify(feHub).send(eq("voice_sentence"), argThatMap("tempId", tempId));

        orchestrator.onProgress(tempId, 1);
        verify(feHub).send(eq("voice_progress"), argThatMap("tempId", tempId));
    }

    @Test
    @DisplayName("'이 문장 다시'는 화면에 떠 있는 번호를 재발급하고, 다시 읽기 전에는 '다음'을 막는다")
    void sentenceRetryReissuesSameNumber() {
        String tempId = startAndGetTempId();
        orchestrator.onReady(tempId);
        orchestrator.onProgress(tempId, 1); // 1번 통과 — 화면에는 1번의 판독 결과

        orchestrator.retrySentence(tempId);

        verify(agentHub, org.mockito.Mockito.times(2)).send(eq("voice_collect"), argThatMap("n", 1));

        orchestrator.nextSentence(tempId); // 재녹음이 아직 통과하지 않았다
        verify(feHub, never()).send(eq("voice_sentence"), argThatMap("n", 2));

        orchestrator.onProgress(tempId, 1);
        orchestrator.nextSentence(tempId);
        verify(feHub).send(eq("voice_sentence"), argThatMap("n", 2));
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

    @Test
    @DisplayName("문장 단위 거절은 tempId·n·total·reason 과 code 를 실어 FE 로 가고, 순번은 진행하지 않는다")
    void sentenceRejectedCarriesCodeAndDoesNotAdvance() {
        String tempId = startAndGetTempId();
        orchestrator.onReady(tempId); // 1번 문장 발급

        orchestrator.onSentenceRejected(tempId, om.readTree(
                "{\"n\":1,\"reason\":\"너무 짧게 들렸어요.\",\"code\":\"TOO_SHORT\"}"));

        verify(feHub).send(eq("voice_sentence_rejected"), argThat(body ->
                body instanceof Map<?, ?> m
                        && tempId.equals(m.get("tempId"))
                        && Integer.valueOf(1).equals(m.get("n"))
                        && Integer.valueOf(5).equals(m.get("total"))
                        && "너무 짧게 들렸어요.".equals(m.get("reason"))
                        && "TOO_SHORT".equals(m.get("code"))));
        verify(feHub, never()).send(eq("voice_sentence"), argThatMap("n", 2));
        verify(agentHub, org.mockito.Mockito.times(1)).send(eq("voice_collect"), any()); // 재발급 없음
    }

    @Test
    @DisplayName("code 가 없으면 키 자체를 넣지 않는다 — FE 는 reason 으로 폴백한다")
    void sentenceRejectedOmitsCodeWhenAbsent() {
        String tempId = startAndGetTempId();

        orchestrator.onSentenceRejected(tempId, om.readTree("{\"n\":2,\"reason\":\"목소리 분석에 실패했어요.\"}"));

        verify(feHub).send(eq("voice_sentence_rejected"), argThat(body ->
                body instanceof Map<?, ?> m && !m.containsKey("code")));
    }

    @Test
    @DisplayName("진행 중 등록과 다른 tempId 의 거절은 무시한다 — 다른 voice_* 수신과 같은 규칙")
    void sentenceRejectedIgnoresUnknownTempId() {
        startAndGetTempId();

        orchestrator.onSentenceRejected("nope", om.readTree("{\"n\":1,\"reason\":\"x\"}"));

        verify(feHub, never()).send(eq("voice_sentence_rejected"), any());
    }

    /** 페이로드 맵에서 키 하나만 보는 매처 — BaseHub.send(String, Object) 의 두 번째 인자용. */
    private static Object argThatMap(String key, Object value) {
        return org.mockito.ArgumentMatchers.argThat(m ->
                m instanceof Map<?, ?> map && value.equals(map.get(key)));
    }
}
