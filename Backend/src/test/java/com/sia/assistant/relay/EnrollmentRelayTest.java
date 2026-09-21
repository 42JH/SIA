package com.sia.assistant.relay;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.argThat;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.inOrder;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.settings.SettingsService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.InOrder;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * 이름 불러보기(호출어 샘플) 중계 — BE 는 세지 않고 그대로 넘긴다 (프로토콜 §8.7).
 * 샘플 수의 원천은 AI 라서 BE 가 total 을 고쳐 쓰면 FE 진행바가 AI 와 어긋난다.
 *
 * <p>가변 호출어 이후 BE 가 지는 책임은 하나 더 있다 — <b>확정 시점</b>.
 * 후보 단어는 등록을 시작할 때가 아니라 {@code wakeword_done} 을 받은 순간 설정에 들어간다.
 * 먼저 저장하면 중간에 그만뒀을 때 설정만 새 단어로 남아 불러도 대답하지 않는 상태가 된다.
 */
class EnrollmentRelayTest {

    private final ObjectMapper om = new ObjectMapper();
    private AgentHub agentHub;
    private FeHub feHub;
    private SettingsService settings;
    private EnrollmentRelay relay;

    @BeforeEach
    void setUp() {
        agentHub = mock(AgentHub.class);
        feHub = mock(FeHub.class);
        settings = mock(SettingsService.class);
        when(settings.peekString("wakeWord")).thenReturn("시아야");
        relay = new EnrollmentRelay(agentHub, feHub, settings);
    }

    @Test
    @DisplayName("시작은 후보 단어를 실어 AI 에만 보낸다 — FE 로는 아무것도 가지 않는다")
    void startGoesToAgentOnly() {
        relay.startWakeword(om.readTree("{\"wakeWord\":\"하늘아\"}"));

        verify(agentHub).send(eq("wakeword_enroll_start"), eq(Map.of("wakeWord", "하늘아")));
        verifyNoInteractions(feHub);
    }

    @Test
    @DisplayName("★ 시작 시점에는 설정을 바꾸지 않는다 — 여기서 저장하면 중단한 사용자가 못 부르는 호출어를 갖게 된다")
    void startDoesNotCommit() {
        relay.startWakeword(om.readTree("{\"wakeWord\":\"하늘아\"}"));

        verify(settings, never()).commitWakeWord(any());
    }

    @Test
    @DisplayName("wakeWord 가 없으면 지금 설정된 호출어로 등록한다 — 고를 기회가 없는 온보딩 경로다")
    void startFallsBackToCurrentSetting() {
        relay.startWakeword(om.readTree("{}"));

        verify(agentHub).send(eq("wakeword_enroll_start"), eq(Map.of("wakeWord", "시아야")));
    }

    @Test
    @DisplayName("글자 규칙에 걸리면 시작 단계에서 끊는다 — 5번을 다 부른 뒤에 거절하면 처음부터 다시 해야 한다")
    void invalidWordNeverReachesAgent() {
        doThrow(new ApiException(ErrorCode.INVALID_REQUEST, "완성된 한글 음절로만 이루어져야 합니다"))
                .when(settings).validateWakeWord("시아A");

        assertThatThrownBy(() -> relay.startWakeword(om.readTree("{\"wakeWord\":\"시아A\"}")))
                .isInstanceOf(ApiException.class);

        verifyNoInteractions(agentHub);
        relay.onWakewordDone();                       // 거절된 단어는 후보로도 남지 않는다
        verify(settings, never()).commitWakeWord(any());
    }

    @Test
    @DisplayName("wakeword_sample 은 n·total 을 그대로 wakeword_progress 로 넘긴다")
    void samplePassesPayloadThrough() {
        JsonNode d = om.readTree("{\"n\":3,\"total\":5}");
        relay.onWakewordSample(d);

        verify(feHub).send(eq("wakeword_progress"), argThat(body ->
                body instanceof JsonNode j && j.path("n").asInt() == 3 && j.path("total").asInt() == 5));
        verifyNoInteractions(agentHub);
    }

    @Test
    @DisplayName("★ wakeword_done 이 호출어를 확정한다 — FE 통지보다 먼저여야 FE 가 새 값을 읽는다")
    void doneCommitsThenRelays() {
        relay.startWakeword(om.readTree("{\"wakeWord\":\"하늘아\"}"));
        relay.onWakewordDone();

        InOrder order = inOrder(settings, feHub);
        order.verify(settings).commitWakeWord("하늘아");
        order.verify(feHub).send(eq("wakeword_done"), eq(Map.of()));
    }

    @Test
    @DisplayName("시작을 거치지 않은 done 은 중계만 한다 — BE 가 재시작하면 확정할 근거가 없다")
    void doneWithoutPendingOnlyRelays() {
        relay.onWakewordDone();

        verify(settings, never()).commitWakeWord(any());
        verify(feHub).send(eq("wakeword_done"), eq(Map.of()));
    }

    @Test
    @DisplayName("거절은 후보를 버리지 않는다 — 재시도이지 종료가 아니다")
    void rejectionKeepsPendingWord() {
        relay.startWakeword(om.readTree("{\"wakeWord\":\"하늘아\"}"));
        relay.onWakewordRejected(om.readTree("{\"n\":3,\"total\":5,\"reason\":\"조금 더 크게\"}"));
        relay.onWakewordDone();

        verify(settings).commitWakeWord("하늘아");
    }

    @Test
    @DisplayName("wakeword_rejected 는 n·total·reason·code 를 그대로 넘긴다 — 순번도 total 도 AI 가 쥔다")
    void rejectionPassesPayloadThrough() {
        JsonNode d = om.readTree(
                "{\"n\":3,\"total\":5,\"reason\":\"주변이 시끄러워요.\",\"code\":\"NOISY\"}");
        relay.onWakewordRejected(d);

        verify(feHub).send(eq("wakeword_rejected"), argThat(body ->
                body instanceof JsonNode j && j.path("n").asInt() == 3 && j.path("total").asInt() == 5
                        && "주변이 시끄러워요.".equals(j.path("reason").asText())
                        && "NOISY".equals(j.path("code").asText())));
        verifyNoInteractions(agentHub);
    }

    @Test
    @DisplayName("중단은 AI 에 wakeword_enroll_cancel 만 보낸다 — FE 로는 아무것도 가지 않는다")
    void cancelGoesToAgentOnly() {
        relay.cancelWakeword();

        verify(agentHub).send(eq("wakeword_enroll_cancel"), eq(Map.of()));
        verifyNoInteractions(feHub);
    }

    @Test
    @DisplayName("★ 중단하면 후보를 버린다 — 뒤늦게 done 이 와도 옛 호출어와 옛 모델의 짝을 깨지 않는다")
    void cancelDropsPendingWord() {
        relay.startWakeword(om.readTree("{\"wakeWord\":\"하늘아\"}"));
        relay.cancelWakeword();
        relay.onWakewordDone();

        verify(settings, never()).commitWakeWord(any());
    }

    @Test
    @DisplayName("거절 본문이 객체가 아니면 빈 객체로 방어한다")
    void nonObjectRejectionFallsBackToEmpty() {
        relay.onWakewordRejected(om.readTree("[1,2]"));

        verify(feHub).send(eq("wakeword_rejected"), eq(Map.of()));
    }

}
