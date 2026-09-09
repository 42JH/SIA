package com.sia.assistant.registration;

import com.fasterxml.jackson.databind.JsonNode;
import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.Sha256;
import com.sia.assistant.profile.VoiceProfileService;
import com.sia.assistant.settings.SettingsService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * 보이스(화자) 등록 오케스트레이터 — 동시 진행 1건 (와이어프레임 보이스 녹음 5문장 흐름, PROTOCOL.md §2.1).
 * 낭독 문장 5개의 원문은 FE·AI 가 동일한 상수로 보유한다(불변, 하드코딩) — BE 는 순번(n)만 정해 양쪽에 보낸다.
 * AI 는 문장 단위로 수집하고(voice_collect), 같은 n 이 다시 오면 그 문장을 교체한다.
 * 임시본(npz·샘플 오디오)은 메모리에만 있다가 사용자의 "등록"(voice_commit)에서 프로필로 확정된다 —
 * 재시작하면 진행 중이던 등록은 사라지는 게 맞고, DB 에 청소할 고아도 남지 않는다.
 */
@Component
public class VoiceRegistrationOrchestrator {

    private static final Logger log = LoggerFactory.getLogger(VoiceRegistrationOrchestrator.class);
    private static final int TOTAL_SENTENCES = 5;
    private static final long MAX_UPLOAD_BYTES = 10L * 1024 * 1024;

    private final AgentHub agentHub;
    private final FeHub feHub;
    private final VoiceProfileService voiceProfileService;
    private final SettingsService settingsService;

    private final AtomicReference<Draft> current = new AtomicReference<>();

    private static final class Draft {
        final String tempId;
        volatile int currentN = 1;
        volatile byte[] npz;
        volatile String npzSha256;
        volatile byte[] sample;
        volatile String sampleMime;
        volatile Double durationSec;
        volatile String quality;
        volatile String noise;

        Draft(String tempId) {
            this.tempId = tempId;
        }
    }

    public VoiceRegistrationOrchestrator(AgentHub agentHub, FeHub feHub,
                                         VoiceProfileService voiceProfileService,
                                         SettingsService settingsService) {
        this.agentHub = agentHub;
        this.feHub = feHub;
        this.voiceProfileService = voiceProfileService;
        this.settingsService = settingsService;
    }

    /** FE voice_reg_start — 한도(4개) 검사 후 tempId 발급, AI 에 등록 모드 진입 지시. */
    public void start() {
        if (voiceProfileService.count() >= VoiceProfileService.MAX_PROFILES) {
            feHub.send("voice_reg_denied", Map.of("message",
                    "보이스는 최대 " + VoiceProfileService.MAX_PROFILES
                            + "개까지 등록할 수 있어요. 사용하지 않는 보이스를 삭제한 뒤 다시 시도해 주세요."));
            return;
        }
        String tempId = UUID.randomUUID().toString().substring(0, 8);
        Draft old = current.getAndSet(new Draft(tempId));
        if (old != null) {
            log.warn("진행 중이던 보이스 등록 {} 을 버리고 새 등록 {} 을 시작합니다", old.tempId, tempId);
        }
        agentHub.send("voice_reg_start", Map.of("tempId", tempId, "total", TOTAL_SENTENCES));
    }

    /** AI voice_ready — 첫 문장 발급. */
    public void onReady(String tempId) {
        Draft draft = match(tempId, "voice_ready");
        if (draft == null) {
            return;
        }
        draft.currentN = 1;
        sendSentence(draft, 1);
    }

    /** AI voice_progress {tempId, n} — 진행률 중계 후 다음 문장. "문장을 다 읽으면 자동으로 다음". */
    public void onProgress(String tempId, int n) {
        Draft draft = match(tempId, "voice_progress");
        if (draft == null) {
            return;
        }
        feHub.send("voice_progress", Map.of("n", n, "total", TOTAL_SENTENCES));
        if (n >= 1 && n < TOTAL_SENTENCES) {
            draft.currentN = n + 1;
            sendSentence(draft, n + 1);
        }
    }

    /** FE voice_sentence_retry — "이 문장 다시". 같은 n 의 voice_collect 를 재발급한다 (AI 는 교체 수집). */
    public void retrySentence(String tempId) {
        Draft draft = match(tempId, "voice_sentence_retry");
        if (draft == null) {
            return;
        }
        sendSentence(draft, draft.currentN);
    }

    /** FE voice_reg_retry — "다시 녹음". 1번 문장부터 다시 (수집물은 AI 가 문장 단위로 교체한다). */
    public void retryAll(String tempId) {
        Draft draft = match(tempId, "voice_reg_retry");
        if (draft == null) {
            return;
        }
        draft.currentN = 1;
        draft.sample = null;
        draft.npz = null;
        sendSentence(draft, 1);
    }

    /** AI voice_quality_warn — "목소리가 잘 들리지 않았어요" 중계. FE 가 [그대로 진행/다시 녹음] 분기. */
    public void onQualityWarn(String tempId, JsonNode d) {
        if (match(tempId, "voice_quality_warn") == null) {
            return;
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("tempId", tempId);
        body.put("reason", d.path("reason").asText(""));
        body.put("noise", d.path("noise").asText(null));
        feHub.send("voice_quality_warn", body);
    }

    /** FE voice_accept_anyway — 경고를 "그대로 진행"으로 무시. AI 에 마무리 지시. */
    public void acceptAnyway(String tempId) {
        if (match(tempId, "voice_accept_anyway") == null) {
            return;
        }
        agentHub.send("voice_finalize", Map.of("tempId", tempId));
    }

    /** AI 의 npz 업로드 (PUT /api/agent/voices/{tempId}/npz). */
    public void attachNpz(String tempId, byte[] payload) {
        Draft draft = requireDraft(tempId);
        requireSize(payload);
        draft.npz = payload;
        draft.npzSha256 = Sha256.hex(payload);
    }

    /** AI 의 샘플 오디오 업로드 (PUT /api/agent/voices/{tempId}/sample). */
    public void attachSample(String tempId, byte[] payload, String mime) {
        Draft draft = requireDraft(tempId);
        requireSize(payload);
        draft.sample = payload;
        draft.sampleMime = mime == null || mime.isBlank() ? "audio/webm" : mime;
    }

    /** 녹음 확인 화면의 재생용 — 아직 프로필이 아니라서 임시 경로로 서빙한다. */
    public VoiceProfileService.Sample draftSample(String tempId) {
        Draft draft = current.get();
        if (draft == null || !draft.tempId.equals(tempId) || draft.sample == null) {
            throw new ApiException(ErrorCode.PROFILE_NOT_FOUND, "재생할 녹음이 없습니다");
        }
        return new VoiceProfileService.Sample(draft.sample, draft.sampleMime);
    }

    /**
     * AI voice_captured — 샘플·npz 업로드가 끝난 뒤 온다.
     * FE 에 녹음 확인 화면(voice_review)을 준다 — 등록 확정은 사용자의 voice_commit 이다.
     */
    public void onCaptured(String tempId, JsonNode d) {
        Draft draft = match(tempId, "voice_captured");
        if (draft == null) {
            return;
        }
        draft.durationSec = d.hasNonNull("durationSec") ? d.path("durationSec").asDouble() : null;
        draft.quality = d.hasNonNull("quality") ? d.path("quality").asText() : null;
        draft.noise = d.hasNonNull("noise") ? d.path("noise").asText() : null;
        if (draft.sample == null || draft.npz == null) {
            log.warn("보이스 등록 {} — voice_captured 가 왔는데 sample/npz 업로드가 없습니다", tempId);
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("tempId", tempId);
        body.put("sampleUrl", draft.sample != null ? "/api/voice-reg/" + tempId + "/sample" : null);
        body.put("durationSec", draft.durationSec);
        body.put("quality", draft.quality);
        body.put("noise", draft.noise);
        feHub.send("voice_review", body);
    }

    /**
     * FE voice_commit {tempId, name?, deviceLabel?} — 프로필 확정.
     * 마이크 이름은 <b>OS 가 보고한 장치 이름</b>이고, 이후 장비 교체 자동 맵핑의 키가 된다.
     * FE 가 `deviceLabel` 로 실제 녹음에 쓴 장치 이름을 보내면 그것을, 없으면 설정 `micDevice` 를 쓴다 —
     * 설정이 null(= 시스템 기본)일 때 실명을 아는 쪽은 장치를 연 FE 이므로 FE 값이 우선이다.
     */
    public void commit(String tempId, String nameOrNull, String deviceLabelOrNull) {
        Draft draft = current.get();
        if (draft == null || !draft.tempId.equals(tempId)) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "진행 중인 보이스 등록이 없습니다");
        }
        if (draft.npz == null) {
            throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "보이스 데이터가 아직 도착하지 않았습니다. 잠시 후 다시 시도해 주세요");
        }
        String deviceLabel = (deviceLabelOrNull != null && !deviceLabelOrNull.isBlank())
                ? deviceLabelOrNull.trim()
                : settingsService.peekString("micDevice");
        if (deviceLabel == null) {
            log.warn("보이스 등록 {} — 마이크 이름을 알 수 없어 장비 라벨 없이 저장합니다"
                    + " (장비 교체 자동 맵핑 대상에서 빠진다)", tempId);
        }
        long id = voiceProfileService.saveNew(nameOrNull, draft.npz, draft.npzSha256,
                draft.sample, draft.sampleMime, draft.durationSec, draft.quality, draft.noise, deviceLabel);
        boolean active = id == orZero(voiceProfileService.activeIdOrNull());

        Map<String, Object> saved = new LinkedHashMap<>();
        saved.put("id", id);
        saved.put("name", nameOf(id));
        saved.put("active", active);
        feHub.send("voice_saved", saved);
        agentHub.send("voice_registered", saved);
        current.compareAndSet(draft, null);
    }

    /** FE voice_reg_cancel — "중단". 임시본 폐기, AI 에 폐기 지시. */
    public void cancel(String tempId) {
        Draft draft = current.get();
        if (draft != null && draft.tempId.equals(tempId)) {
            current.compareAndSet(draft, null);
        }
        agentHub.send("voice_reg_cancel", Map.of("tempId", tempId));
    }

    // ------------------------------------------------------------------ 내부

    /** 문장 n 의 순번만 보낸다 — 원문은 FE·AI 가 각자의 상수에서 n 번째를 꺼낸다. */
    private void sendSentence(Draft draft, int n) {
        feHub.send("voice_sentence", Map.of("n", n, "total", TOTAL_SENTENCES));
        agentHub.send("voice_collect", Map.of("tempId", draft.tempId, "n", n));
    }

    private Draft match(String tempId, String of) {
        Draft draft = current.get();
        if (draft == null || !draft.tempId.equals(tempId)) {
            log.debug("모르는 보이스 등록 {} 의 {} 무시", tempId, of);
            return null;
        }
        return draft;
    }

    private Draft requireDraft(String tempId) {
        Draft draft = current.get();
        if (draft == null || !draft.tempId.equals(tempId)) {
            throw new ApiException(ErrorCode.PROFILE_NOT_FOUND, "진행 중인 보이스 등록이 없습니다: " + tempId);
        }
        return draft;
    }

    private static void requireSize(byte[] payload) {
        if (payload == null || payload.length < 1 || payload.length > MAX_UPLOAD_BYTES) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "업로드 크기는 1바이트 이상 10MB 이하여야 합니다");
        }
    }

    private String nameOf(long id) {
        try {
            for (Map<String, Object> item : voiceProfileService.list()) {
                if (((Number) item.get("id")).longValue() == id) {
                    return (String) item.get("name");
                }
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    private static long orZero(Long v) {
        return v == null ? 0 : v;
    }
}
