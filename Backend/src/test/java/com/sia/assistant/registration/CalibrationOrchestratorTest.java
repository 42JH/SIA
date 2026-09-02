package com.sia.assistant.registration;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.logging.UsageEventBatchWriter;
import com.sia.assistant.profile.CalibProfileService;
import com.sia.assistant.settings.SettingsService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

/**
 * ★ 재측정("다시 측정")은 보정 세션당 최대 3회이고 BE 가 센다 — 회의 확정 2026-09-01.
 * 그만두기는 임시본을 버려 이전 보정을 유지하고, 완료만 프로필을 만든다.
 */
class CalibrationOrchestratorTest {

    private final ObjectMapper om = new ObjectMapper();
    private AgentHub agentHub;
    private FeHub feHub;
    private CalibProfileService calibProfiles;
    private SettingsService settingsService;
    private CalibrationOrchestrator orchestrator;

    @BeforeEach
    void setUp() {
        agentHub = mock(AgentHub.class);
        feHub = mock(FeHub.class);
        calibProfiles = mock(CalibProfileService.class);
        settingsService = mock(SettingsService.class);
        orchestrator = new CalibrationOrchestrator(agentHub, feHub, calibProfiles, settingsService,
                mock(UsageEventBatchWriter.class));
    }

    private String startAndGetTempId() {
        when(calibProfiles.count()).thenReturn(0);
        orchestrator.start();
        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(agentHub).send(eq("calib_start"), captor.capture());
        return (String) captor.getValue().get("tempId");
    }

    @Test
    @DisplayName("재측정은 3회까지 — 4번째는 AI 에 보내지 않고 FE 에 calib_limit 를 회신한다")
    void remeasureCappedAtThree() {
        startAndGetTempId();

        orchestrator.restart();
        orchestrator.restart();
        orchestrator.restart();
        verify(agentHub, times(3)).send(eq("calib_restart"), any());

        orchestrator.restart(); // 4번째
        verify(agentHub, times(3)).send(eq("calib_restart"), any()); // 그대로 3회
        verify(feHub).send(eq("calib_limit"), any());
    }

    @Test
    @DisplayName("calib_result 는 통과 여부·기준(50px)·남은 재측정 횟수를 붙여 FE 로 나간다")
    void resultCarriesPassAndBudget() throws Exception {
        String tempId = startAndGetTempId();
        orchestrator.restart(); // 1회 사용

        orchestrator.onResult(tempId, om.readTree(
                "{\"tempId\":\"" + tempId + "\",\"avgErrorPx\":38.0,\"maxErrorPx\":62.0,\"points\":[]}"));

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(feHub).send(eq("calib_result"), captor.capture());
        assertThat(captor.getValue())
                .containsEntry("pass", true)
                .containsEntry("thresholdPx", 50.0)
                .containsEntry("remeasuresUsed", 1)
                .containsEntry("remeasuresLeft", 2);
    }

    @Test
    @DisplayName("완료는 결과·npz 가 다 있어야 하고, 프로필에 카메라 이름이 찍힌다")
    void commitRequiresResultAndStampsDevice() throws Exception {
        String tempId = startAndGetTempId();
        assertThatThrownBy(() -> orchestrator.commit(null, null))
                .isInstanceOfSatisfying(ApiException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.INVALID_REQUEST));

        orchestrator.attachNpz(tempId, new byte[]{1}, 1920, 1080);
        orchestrator.onResult(tempId, om.readTree(
                "{\"tempId\":\"" + tempId + "\",\"avgErrorPx\":38.0,\"maxErrorPx\":62.0,\"points\":[]}"));
        when(settingsService.peekString("cameraDevice")).thenReturn("HD Webcam");
        when(calibProfiles.saveNew(any(), any(), any(), any(), any(), any(), any(), any(), any()))
                .thenReturn(7L);
        when(calibProfiles.activeIdOrNull()).thenReturn(7L);
        when(calibProfiles.get(7L)).thenReturn(Map.of("name", "내 보정 1"));

        orchestrator.commit(null, null);

        verify(calibProfiles).saveNew(eq(null), any(), anyString(), eq(1920), eq(1080),
                eq(38.0), eq(62.0), anyString(), eq("HD Webcam"));
        verify(feHub).send(eq("calib_saved"), any());
        verify(agentHub).send(eq("calib_registered"), any());
    }

    @Test
    @DisplayName("그만두기는 임시본을 버리고 AI 에 calib_cancel 을 보낸다 — 이전 보정이 유지된다")
    void cancelDiscardsSession() {
        startAndGetTempId();
        orchestrator.cancel();

        verify(agentHub).send(eq("calib_cancel"), any());
        assertThatThrownBy(() -> orchestrator.commit(null, null))
                .isInstanceOf(ApiException.class);
        verify(calibProfiles, never()).saveNew(any(), any(), any(), any(), any(), any(), any(), any(), any());
    }

    @Test
    @DisplayName("프로필이 4개 차 있으면 보정을 시작하지 않고 calib_denied 를 회신한다")
    void deniedWhenFull() {
        when(calibProfiles.count()).thenReturn(CalibProfileService.MAX_PROFILES);
        orchestrator.start();
        verify(feHub).send(eq("calib_denied"), any());
        verify(agentHub, never()).send(eq("calib_start"), any());
    }
}
