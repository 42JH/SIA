package com.sia.assistant.relay;

import com.sia.assistant.settings.SettingsService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

/**
 * 온보딩 마이크 설정의 첫 단계 "이름 불러보기" 중계 (와이어프레임 온보딩 섹션):
 * 호출어 샘플 수집의 진행률만 FE 로 넘기고, 모델은 AI 가 PUT /api/agent/blobs/wakeword 로 올린다.
 * 거절 사유와 중단도 해석 없이 그대로 흘린다 — 판정도 수집 상태도 AI 가 들고 있어서 BE 가 볼 것은 없다.
 * 다음 단계(명령하듯 5문장 낭독 → 화자 임베딩 → 녹음 확인)는 VoiceRegistrationOrchestrator 가 맡는다 —
 * 옛 "명령 문장 말하기"(command_*) 는 같은 5문장을 한 번 더 읽히기만 하던 중복 단계여서 없앴다.
 *
 * <p><b>가변 호출어(2026-09-21)</b> — 사용자가 부를 이름을 고를 수 있게 되면서 이 클래스가 딱 하나를
 * 들게 됐다: <b>등록 중인 후보 단어</b>. 설정의 호출어는 등록을 시작할 때가 아니라
 * {@code wakeword_done} 을 받은 순간 바뀐다. 먼저 저장해 두면 중간에 그만뒀을 때 설정만 새 단어로
 * 남아 <b>불러도 대답하지 않는 상태</b>가 되기 때문이다 (보이스 등록의 tempId → voice_commit 과 같은 자리).
 * 후보는 메모리에만 있다 — BE 가 재시작하면 진행 중이던 등록은 사라지는 게 맞다.
 */
@Component
public class EnrollmentRelay {

    private static final Logger log = LoggerFactory.getLogger(EnrollmentRelay.class);

    private final AgentHub agentHub;
    private final FeHub feHub;
    private final SettingsService settingsService;

    /** 등록 중인 후보 호출어. null 이면 진행 중인 등록이 없다 (또는 BE 가 재시작했다). */
    private volatile String pendingWakeWord;

    public EnrollmentRelay(AgentHub agentHub, FeHub feHub, SettingsService settingsService) {
        this.agentHub = agentHub;
        this.feHub = feHub;
        this.settingsService = settingsService;
    }

    /**
     * FE wakeword_enroll_start {wakeWord?} — 이름 불러보기 시작.
     * {@code wakeWord} 가 없으면 지금 설정된 호출어로 등록한다 (온보딩 경로 — 고를 기회가 없었다).
     * 글자 규칙(SettingsSchema)에 걸리면 여기서 끊는다: 5번을 다 부르고 나서 거절하면 사용자가 처음부터 다시 해야 한다.
     * AI 에는 <b>항상</b> 단어를 실어 보낸다 — 무엇과 비교해 MISMATCH 를 판정할지가 그 값이다.
     */
    public void startWakeword(JsonNode d) {
        String requested = d != null && d.hasNonNull("wakeWord") ? d.path("wakeWord").asText() : null;
        String word = requested != null && !requested.isBlank()
                ? requested
                : settingsService.peekString("wakeWord");
        settingsService.validateWakeWord(word);   // 틀리면 INVALID_REQUEST → BaseHub 가 FE 에 error 회신
        pendingWakeWord = word;
        agentHub.send("wakeword_enroll_start", Map.of("wakeWord", word));
    }

    /**
     * FE wakeword_enroll_cancel — 등록 화면 이탈·중단. AI 에 수집 종료를 알린다 (보이스의 voice_reg_cancel 과 같은 자리).
     * tempId 는 받지 않는다 — 호출어 템플릿은 전역 blob 1개고 동시 진행도 1건이라 지목할 대상이 없다.
     * 알리지 않으면 AI 가 수집 모드로 남아 이후 발화를 전부 샘플로 먹는다 (음성 명령이 통째로 죽는다).
     * 후보 단어는 버린다 — 설정은 손대지 않았으므로 옛 호출어와 옛 모델이 짝이 맞은 채로 남는다.
     */
    public void cancelWakeword() {
        pendingWakeWord = null;
        agentHub.send("wakeword_enroll_cancel", Map.of());
    }

    /** AI wakeword_sample {n, total} → FE wakeword_progress (페이로드 그대로 — 샘플 수의 원천은 AI 다). */
    public void onWakewordSample(JsonNode d) {
        feHub.send("wakeword_progress", d != null && d.isObject() ? d : Map.of());
    }

    /**
     * AI wakeword_rejected {n, total, reason, code?} → FE 로 페이로드 그대로.
     * n 도 total 도 손대지 않는다 — 거절돼도 순번은 그대로고 AI 가 같은 n 을 계속 기다린다.
     * 호출어 모델 저장 실패도 같은 이벤트로 온다. 그때는 다음 발화가 새 샘플이 아니라 저장 재시도라서,
     * 여기서 사유가 끊기면 사용자는 5/5 에서 다시 불러야 할 이유를 모른 채 갇힌다.
     * 후보 단어는 그대로 둔다 — 거절은 재시도이지 종료가 아니다.
     */
    public void onWakewordRejected(JsonNode d) {
        feHub.send("wakeword_rejected", d != null && d.isObject() ? d : Map.of());
    }

    /**
     * AI wakeword_done — 모델이 만들어졌다. 이 순간에만 설정의 호출어가 바뀐다.
     * 확정을 FE 통지보다 먼저 하는 이유: FE 는 done 을 받고 설정을 다시 읽으므로 순서가 뒤집히면 옛 값을 본다.
     * 후보가 없으면(BE 재시작 · 시작을 거치지 않은 done) 중계만 한다 — 확정할 근거가 없다.
     */
    public void onWakewordDone() {
        String word = pendingWakeWord;
        pendingWakeWord = null;
        if (word != null) {
            settingsService.commitWakeWord(word);
        } else {
            log.warn("wakeword_done 을 받았지만 등록 중인 후보 호출어가 없습니다 — 설정은 그대로 두고 중계만 합니다");
        }
        feHub.send("wakeword_done", Map.of());
    }
}
