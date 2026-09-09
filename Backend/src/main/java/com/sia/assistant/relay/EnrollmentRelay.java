package com.sia.assistant.relay;

import com.fasterxml.jackson.databind.JsonNode;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.util.Map;
import java.util.concurrent.atomic.AtomicInteger;
import org.springframework.stereotype.Component;

/**
 * 온보딩 마이크 설정의 앞 두 단계 중계 (와이어프레임 온보딩 섹션):
 *  1) 이름 불러보기 — 호출어 샘플 10개 수집. 진행률만 중계하고 모델은 AI 가
 *     PUT /api/agent/blobs/wakeword 로 올린다.
 *  2) 명령 문장 말하기 — 문장 5개의 원문은 FE·AI 가 동일한 상수로 보유한다(불변, 하드코딩).
 *     BE 는 원문을 보내지 않고 순번(n)만 정해 FE(command_sentence)·AI(command_collect) 양쪽에 준다.
 * 세 번째 단계(보이스 녹음 5문장)는 VoiceRegistrationOrchestrator 가 맡는다.
 */
@Component
public class EnrollmentRelay {

    private static final int COMMAND_TOTAL = 5;

    private final AgentHub agentHub;
    private final FeHub feHub;
    private final AtomicInteger commandN = new AtomicInteger(0);

    public EnrollmentRelay(AgentHub agentHub, FeHub feHub) {
        this.agentHub = agentHub;
        this.feHub = feHub;
    }

    // ------------------------------------------------------- 이름 불러보기 (호출어)

    public void startWakeword() {
        agentHub.send("wakeword_enroll_start", Map.of());
    }

    /** AI wakeword_sample {n, total} → FE wakeword_progress (페이로드 그대로). */
    public void onWakewordSample(JsonNode d) {
        feHub.send("wakeword_progress", d != null && d.isObject() ? d : Map.of());
    }

    public void onWakewordDone() {
        feHub.send("wakeword_done", Map.of());
    }

    // ------------------------------------------------------- 명령 문장 말하기

    public void startCommand() {
        commandN.set(0);
        agentHub.send("command_enroll_start", Map.of());
    }

    public void onCommandReady() {
        commandN.set(1);
        sendCommandSentence(1);
    }

    /** AI command_progress {n} — 진행률 중계 후 다음 문장. */
    public void onCommandProgress(JsonNode d) {
        int n = d.path("n").asInt();
        feHub.send("command_progress", Map.of("n", n, "total", COMMAND_TOTAL));
        if (n >= 1 && n < COMMAND_TOTAL) {
            commandN.set(n + 1);
            sendCommandSentence(n + 1);
        }
    }

    public void onCommandDone() {
        feHub.send("command_done", Map.of());
    }

    // ------------------------------------------------------------------ 내부

    /** 문장 n 의 순번만 보낸다 — 원문은 FE·AI 가 각자의 상수에서 n 번째를 꺼낸다. */
    private void sendCommandSentence(int n) {
        feHub.send("command_sentence", Map.of("n", n, "total", COMMAND_TOTAL));
        agentHub.send("command_collect", Map.of("n", n));
    }
}
