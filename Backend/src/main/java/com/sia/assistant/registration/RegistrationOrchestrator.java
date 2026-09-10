package com.sia.assistant.registration;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.Sha256;
import com.sia.assistant.config.DataDirs;
import com.sia.assistant.settings.GestureService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import jakarta.annotation.PreDestroy;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * 커스텀 제스처 등록 오케스트레이터 — 동시 등록은 1건 (와이어프레임 제스처 촬영 흐름).
 * ★ 촬영은 "3초 카운트다운 후 2초간 3회 반복" — 회차(take)별로 프레임을 버퍼링해
 *   회차별 미리보기 webm 을 만들고, 사용자가 고른 회차가 제스처 영상·템플릿이 된다.
 * ★ 등록 영상은 매크로 지정 시 previews/ 에서 gestures/ 로 옮겨 영구 보관한다 —
 *   목록·상세 화면이 다시 보여 준다 (회의 확정: "등록 때 사용한 영상 저장, 조회 시 FE 전송").
 * ★2026-09-02 흐름도 03 정합: 템플릿 npz 는 제스처별이다. AI 가 reg_captured 전에
 *   PUT /api/agent/gestures/{tempId}/npz 로 올리면 여기 메모리(임시본)에 있다가, macro_assign 이
 *   gesture 행에 확정한다. npz 없이는 확정할 수 없다 (보이스 등록의 voice_commit 과 같은 규칙).
 * reg_start {replaceGestureId} 면 기존 제스처의 동작 재촬영이다 — 그 행의 템플릿을 교체한다.
 */
@Component
public class RegistrationOrchestrator {

    private static final Logger log = LoggerFactory.getLogger(RegistrationOrchestrator.class);
    private static final int TAKES = 3;
    private static final int COUNTDOWN_SEC = 3;
    private static final int TAKE_DURATION_SEC = 2;
    private static final int MAX_FRAMES = 3000;              // 전 회차 합
    private static final long MAX_BYTES = 256L * 1024 * 1024;

    private final AgentHub agentHub;
    private final FeHub feHub;
    private final GestureService gestureService;
    private final WebmEncoder encoder;
    private final PreviewStore previewStore;
    private final DataDirs dataDirs;
    private final ObjectMapper om;

    // 인코딩은 CPU·디스크를 쓰는 긴 작업 — WS 스레드가 아니라 여기서만 돈다.
    private final ExecutorService encodeExecutor = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "reg-encoder");
        t.setDaemon(true);
        return t;
    });

    private final AtomicReference<Reg> current = new AtomicReference<>();

    /** 진행 중인 등록 1건의 상태. 프레임·npz 접근은 인스턴스 동기화로 보호한다. */
    private static final class Reg {
        final String tempId;
        final Long replaceGestureId;                          // null 이면 신규 등록
        final TreeMap<Integer, ArrayDeque<WebmEncoder.Frame>> takeFrames = new TreeMap<>();
        long totalBytes;
        long totalFrames;
        boolean overflowWarned;
        boolean recordingNotified;
        byte[] npz;                                           // AI 가 PUT 한 템플릿 임시본 — assign 에서 행이 된다
        String npzSha256;

        Reg(String tempId, Long replaceGestureId) {
            this.tempId = tempId;
            this.replaceGestureId = replaceGestureId;
        }
    }

    public RegistrationOrchestrator(AgentHub agentHub, FeHub feHub, GestureService gestureService,
                                    WebmEncoder encoder, PreviewStore previewStore, DataDirs dataDirs,
                                    ObjectMapper om) {
        this.agentHub = agentHub;
        this.feHub = feHub;
        this.gestureService = gestureService;
        this.encoder = encoder;
        this.previewStore = previewStore;
        this.dataDirs = dataDirs;
        this.om = om;
    }

    /** 등록 시작 — tempId 발급, AI 에 등록 모드(촬영 파라미터 포함) 가동 지시. */
    public String start(Long replaceGestureIdOrNull) {
        String replaceName = null;
        if (replaceGestureIdOrNull != null) {
            replaceName = (String) gestureService.getOne(replaceGestureIdOrNull).get("name");
        }
        String tempId = UUID.randomUUID().toString().substring(0, 8);
        Reg old = current.getAndSet(new Reg(tempId, replaceGestureIdOrNull));
        if (old != null) {
            log.warn("진행 중이던 등록 {} 을 버리고 새 등록 {} 을 시작합니다", old.tempId, tempId);
            previewStore.discard(old.tempId); // 버린 등록의 미리보기는 아무도 고를 수 없다
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("tempId", tempId);
        body.put("takes", TAKES);
        body.put("countdownSec", COUNTDOWN_SEC);
        body.put("takeDurationSec", TAKE_DURATION_SEC);
        if (replaceName != null) {
            body.put("replaceGestureName", replaceName);
        }
        agentHub.send("reg_mode_start", body);
        return tempId;
    }

    public void onRegStarted(String tempId) {
        if (mismatch(tempId, "reg_started")) {
            return;
        }
        feHub.send("reg_state", Map.of("tempId", tempId, "phase", "MODE_STARTED"));
    }

    /** AI reg_take {tempId, take, phase} — "2/3회 녹화 중" 진행 중계. */
    public void onTake(String tempId, JsonNode d) {
        if (mismatch(tempId, "reg_take")) {
            return;
        }
        feHub.send("reg_take", d != null && d.isObject() ? d : Map.of());
    }

    /** AI 가 보낸 압축 프레임 — 회차별 버퍼링(상한 가드) + FE 실시간 미리보기 중계(받은 jpegB64 그대로). */
    public void onFrame(String tempId, int take, long seq, long tsMs, String jpegB64) {
        Reg reg = current.get();
        if (reg == null || !reg.tempId.equals(tempId)) {
            log.debug("모르는 등록 {} 의 프레임 무시 (seq={})", tempId, seq);
            return;
        }
        byte[] jpeg;
        try {
            jpeg = Base64.getDecoder().decode(jpegB64);
        } catch (IllegalArgumentException e) {
            log.warn("등록 {} 프레임 {} Base64 디코딩 실패 — 건너뜀", tempId, seq);
            return;
        }
        int safeTake = Math.min(Math.max(take, 1), TAKES);
        boolean first;
        synchronized (reg) {
            reg.takeFrames.computeIfAbsent(safeTake, k -> new ArrayDeque<>())
                    .addLast(new WebmEncoder.Frame(seq, tsMs, jpeg));
            reg.totalBytes += jpeg.length;
            reg.totalFrames++;
            while (reg.totalFrames > MAX_FRAMES || reg.totalBytes > MAX_BYTES) {
                ArrayDeque<WebmEncoder.Frame> oldest = reg.takeFrames.firstEntry() == null
                        ? null : reg.takeFrames.firstEntry().getValue();
                WebmEncoder.Frame dropped = oldest == null ? null : oldest.pollFirst();
                if (dropped == null) {
                    break;
                }
                reg.totalBytes -= dropped.jpeg().length;
                reg.totalFrames--;
                if (!reg.overflowWarned) {
                    reg.overflowWarned = true;
                    log.warn("등록 {} 프레임 버퍼 상한 초과 — 오래된 프레임부터 버립니다", tempId);
                }
            }
            first = !reg.recordingNotified;
            reg.recordingNotified = true;
        }
        if (first) {
            feHub.send("reg_state", Map.of("tempId", tempId, "phase", "RECORDING"));
        }
        feHub.send("reg_frame", Map.of("tempId", tempId, "take", safeTake, "seq", seq, "jpegB64", jpegB64));
    }

    /** 등록 구간 종료 — AI 에 종료 지시 후 회차별 백그라운드 인코딩. */
    public void stop(String tempId) {
        Reg reg = current.get();
        if (reg == null || !reg.tempId.equals(tempId)) {
            log.warn("모르는 등록 {} 의 종료 요청 무시", tempId);
            return;
        }
        agentHub.send("reg_finish", Map.of("tempId", tempId));
        feHub.send("reg_state", Map.of("tempId", tempId, "phase", "ENCODING"));

        Map<Integer, List<WebmEncoder.Frame>> snapshot = new TreeMap<>();
        synchronized (reg) {
            reg.takeFrames.forEach((take, frames) -> snapshot.put(take, new ArrayList<>(frames)));
            reg.takeFrames.clear(); // 버퍼는 여기서 해제 — 인코더는 복사본으로 작업한다
            reg.totalBytes = 0;
            reg.totalFrames = 0;
        }
        encodeExecutor.submit(() -> encodeAndNotify(tempId, snapshot));
    }

    private void encodeAndNotify(String tempId, Map<Integer, List<WebmEncoder.Frame>> takes) {
        Path previews = dataDirs.previews();
        List<Map<String, Object>> results = new ArrayList<>();
        for (Map.Entry<Integer, List<WebmEncoder.Frame>> entry : takes.entrySet()) {
            String baseName = tempId + "-" + entry.getKey();
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("take", entry.getKey());
            try {
                encoder.encode(baseName, entry.getValue(), previews);
                item.put("webmUrl", "/api/previews/" + baseName + ".webm");
            } catch (Exception e) {
                log.warn("등록 {} 회차 {} 미리보기 인코딩 실패", tempId, entry.getKey(), e);
                item.put("webmUrl", null);
            }
            results.add(item);
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("tempId", tempId);
        body.put("takes", results);
        if (results.isEmpty() || results.stream().allMatch(r -> r.get("webmUrl") == null)) {
            body.put("reason", "영상 인코딩에 실패했습니다");
        }
        feHub.send("reg_recorded", body);
    }

    /** AI 품질 검증 미달 — 버퍼 폐기 + FE 통지 (유사 제스처 정보 포함 가능). 사용자는 다시 촬영한다. */
    public void onRejected(String tempId, JsonNode d) {
        Reg reg = current.get();
        if (reg != null && reg.tempId.equals(tempId)) {
            current.compareAndSet(reg, null);
        }
        previewStore.discard(tempId); // 인코딩까지 갔더라도 거절된 촬영본은 남기지 않는다
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("tempId", tempId);
        body.put("phase", "REJECTED");
        body.put("reason", d.path("reason").asText(""));
        if (d.hasNonNull("similarTo")) {
            body.put("similarTo", d.path("similarTo").asText());   // "주먹 쥐기"
        }
        if (d.hasNonNull("similarity")) {
            body.put("similarity", d.path("similarity").asDouble()); // 0.87 → FE "유사도 87%"
        }
        feHub.send("reg_state", body);
    }

    /**
     * AI 의 템플릿 npz 업로드 (PUT /api/agent/gestures/{tempId}/npz) — reg_captured 전에 온다.
     * 확정 전이라 임시본은 여기 메모리에만 있다 (BE 재기동 시 진행 중 등록은 사라진다). 다시 올리면 교체된다.
     */
    public void attachNpz(String tempId, byte[] payload) {
        Reg reg = current.get();
        if (reg == null || !reg.tempId.equals(tempId)) {
            throw new ApiException(ErrorCode.GESTURE_NOT_FOUND, "진행 중인 제스처 등록이 없습니다: " + tempId);
        }
        if (payload == null || payload.length < GestureService.NPZ_MIN_BYTES
                || payload.length > GestureService.NPZ_MAX_BYTES) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "업로드 크기는 1바이트 이상 5MB 이하여야 합니다");
        }
        synchronized (reg) {
            reg.npz = payload;
            reg.npzSha256 = Sha256.hex(payload);
        }
    }

    /** AI reg_captured — 템플릿 후보 확정(검증 통과). npz 는 이 앞에 PUT 되어 있어야 한다. */
    public void onCaptured(String tempId) {
        if (mismatch(tempId, "reg_captured")) {
            return;
        }
        Reg reg = current.get();
        synchronized (reg) {
            if (reg.npz == null) {
                log.warn("등록 {} — reg_captured 가 왔지만 템플릿 npz 가 아직 없습니다. macro_assign 전에 PUT 되어야 합니다",
                        tempId);
            }
        }
        feHub.send("reg_state", Map.of("tempId", tempId, "phase", "CAPTURED"));
    }

    /**
     * 매크로 지정 — 템플릿 npz 와 함께 gesture 행으로 확정하고, 고른 회차(take)의 미리보기를 제스처 영상으로 승격,
     * AI 확정 통지(gesture_registered {id, sha256} — AI 는 GET /api/agent/gestures/{id}/npz 로 내려받는다)
     * + FE 완료 통지(macro_saved). 진행 중 등록과 tempId 가 다르거나 npz 가 없으면 거절한다.
     */
    public void assign(JsonNode d) {
        String tempId = d.path("tempId").asText("");
        int take = Math.min(Math.max(d.path("take").asInt(1), 1), TAKES);
        String name = d.path("name").asText("");
        if (name.isBlank()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "제스처 이름이 필요합니다");
        }
        String label = d.hasNonNull("label") ? d.path("label").asText() : null;
        String context = d.hasNonNull("context") ? d.path("context").asText() : null;
        String description = d.hasNonNull("description") ? d.path("description").asText() : null;
        boolean repeatable = d.path("repeatable").asBoolean(false);

        List<GestureService.Step> steps = new ArrayList<>();
        for (JsonNode s : d.path("steps")) {
            String tool = s.path("tool").asText("");
            if (tool.isBlank()) {
                throw new ApiException(ErrorCode.INVALID_REQUEST, "각 단계에는 tool 이 필요합니다");
            }
            Map<String, Object> args = s.hasNonNull("args")
                    ? om.convertValue(s.path("args"), new TypeReference<Map<String, Object>>() { })
                    : Map.of();
            Integer delayMs = s.hasNonNull("delayMs") ? s.path("delayMs").asInt() : null;
            steps.add(new GestureService.Step(tool, args, delayMs));
        }

        Reg reg = current.get();
        if (reg == null || !reg.tempId.equals(tempId)) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "진행 중인 제스처 등록이 없습니다. 등록을 다시 시작해 주세요");
        }
        byte[] npz;
        String npzSha256;
        synchronized (reg) {
            npz = reg.npz;
            npzSha256 = reg.npzSha256;
        }
        if (npz == null) {
            throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "제스처 템플릿이 아직 도착하지 않았습니다. 잠시 후 다시 시도해 주세요");
        }

        Long replaceId = reg.replaceGestureId;
        long gestureId;
        if (replaceId != null) {
            gestureService.updateCustom(replaceId, name, label, description, repeatable,
                    steps.isEmpty() ? null : steps);
            gestureService.updateNpz(replaceId, npz, npzSha256);
            gestureId = replaceId;
        } else {
            gestureId = gestureService.saveCustom(name, label, context, description, repeatable, steps,
                    npz, npzSha256);
        }

        String videoUrl = promoteVideo(tempId, take, gestureId);

        Map<String, Object> registered = new LinkedHashMap<>();
        registered.put("tempId", tempId);
        registered.put("take", take);
        registered.put("id", gestureId);
        registered.put("name", name);
        registered.put("label", label);
        registered.put("sha256", npzSha256);
        agentHub.send("gesture_registered", registered);

        Map<String, Object> saved = new LinkedHashMap<>();
        saved.put("id", gestureId);
        saved.put("name", name);
        saved.put("videoUrl", videoUrl);
        feHub.send("macro_saved", saved);

        current.compareAndSet(reg, null); // 등록 사이클 완료 — 상태(임시 npz 포함) 해제
    }

    /**
     * previews/{tempId}-{take}.webm → gestures/g{gestureId}.webm 승격. 실패해도 저장 자체는 성립한다.
     * 승격이 끝나면 고른 회차를 포함해 그 등록의 미리보기를 모두 버린다 — 승격본이 gestures/ 에 있다.
     * 실패했을 때는 남겨 둔다(원본이 있어야 재촬영 없이 다시 손쓸 수 있다).
     */
    private String promoteVideo(String tempId, int take, long gestureId) {
        if (tempId.isBlank()) {
            return null;
        }
        Path source = dataDirs.previews().resolve(tempId + "-" + take + ".webm");
        if (!Files.isRegularFile(source)) {
            log.warn("등록 {} 회차 {} 미리보기가 없어 제스처 영상을 남기지 못했습니다", tempId, take);
            return null;
        }
        String fileName = "g" + gestureId + ".webm";
        try {
            Files.copy(source, dataDirs.gestures().resolve(fileName), StandardCopyOption.REPLACE_EXISTING);
            gestureService.setVideoPath(gestureId, fileName);
            previewStore.discard(tempId);
            return "/api/gestures/" + gestureId + "/video";
        } catch (Exception e) {
            log.warn("제스처 {} 영상 보관 실패", gestureId, e);
            return null;
        }
    }

    private boolean mismatch(String tempId, String of) {
        Reg reg = current.get();
        if (reg == null || !reg.tempId.equals(tempId)) {
            log.debug("모르는 등록 {} 의 {} 무시", tempId, of);
            return true;
        }
        return false;
    }

    @PreDestroy
    void shutdown() {
        encodeExecutor.shutdownNow();
    }
}
