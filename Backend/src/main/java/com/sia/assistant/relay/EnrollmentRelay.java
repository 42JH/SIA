package com.sia.assistant.relay;

import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.util.Map;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

/**
 * 온보딩 마이크 설정의 첫 단계 "이름 불러보기" 중계 (와이어프레임 온보딩 섹션):
 * 호출어 샘플 수집의 진행률만 FE 로 넘기고, 모델은 AI 가 PUT /api/agent/blobs/wakeword 로 올린다.
 * 거절 사유와 중단도 해석 없이 그대로 흘린다 — 판정도 수집 상태도 AI 가 들고 있어서 BE 가 볼 것은 없다.
 * 다음 단계(명령하듯 5문장 낭독 → 화자 임베딩 → 녹음 확인)는 VoiceRegistrationOrchestrator 가 맡는다 —
 * 옛 "명령 문장 말하기"(command_*) 는 같은 5문장을 한 번 더 읽히기만 하던 중복 단계여서 없앴다.
 */
@Component
public class EnrollmentRelay {

    private final AgentHub agentHub;
    private final FeHub feHub;

    public EnrollmentRelay(AgentHub agentHub, FeHub feHub) {
        this.agentHub = agentHub;
        this.feHub = feHub;
    }

    public void startWakeword() {
        agentHub.send("wakeword_enroll_start", Map.of());
    }

    /**
     * FE wakeword_enroll_cancel — 등록 화면 이탈·중단. AI 에 수집 종료를 알린다 (보이스의 voice_reg_cancel 과 같은 자리).
     * tempId 는 받지 않는다 — 호출어 템플릿은 전역 blob 1개고 동시 진행도 1건이라 지목할 대상이 없다.
     * 알리지 않으면 AI 가 수집 모드로 남아 이후 발화를 전부 샘플로 먹는다 (음성 명령이 통째로 죽는다).
     */
    public void cancelWakeword() {
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
     */
    public void onWakewordRejected(JsonNode d) {
        feHub.send("wakeword_rejected", d != null && d.isObject() ? d : Map.of());
    }

    public void onWakewordDone() {
        feHub.send("wakeword_done", Map.of());
    }
}
