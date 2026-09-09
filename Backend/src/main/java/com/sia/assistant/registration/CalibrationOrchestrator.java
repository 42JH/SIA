package com.sia.assistant.registration;

import com.fasterxml.jackson.databind.JsonNode;
import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.Sha256;
import com.sia.assistant.logging.UsageEventBatchWriter;
import com.sia.assistant.profile.CalibProfileService;
import com.sia.assistant.settings.SettingsService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * 시선 보정 오케스트레이터 — 동시 진행 1건 (와이어프레임 시선 섹션, PROTOCOL.md §2.2).
 * ★ 재측정("다시 측정")은 보정 세션당 최대 3회이고 그 카운트는 BE(여기)가 센다 —
 *   사용자가 요구했든 오차 등급이 나빠 FE 가 유도했든 같은 카운트다.
 * ★ 오차 기준은 AI 서버가 관리한다 — BE 는 AI 가 보낸 grade·pass 를 중계하고 프로필에 적기만 한다.
 * 임시본(npz·결과)은 메모리에만 있다가 "완료"(calib_commit)에서 프로필로 확정된다.
 * "그만두기"(calib_cancel)면 폐기 — 이전 시선 데이터가 그대로 유지된다 (와이어프레임 중단 다이얼로그).
 */
@Component
public class CalibrationOrchestrator {

    /** 재측정 한도 — 회의 확정 사항 (2026-09-01). 최초 측정은 세지 않는다. */
    static final int MAX_REMEASURES = 3;

    private static final Logger log = LoggerFactory.getLogger(CalibrationOrchestrator.class);
    private static final long MAX_UPLOAD_BYTES = 5L * 1024 * 1024;

    private final AgentHub agentHub;
    private final FeHub feHub;
    private final CalibProfileService calibProfileService;
    private final SettingsService settingsService;
    private final UsageEventBatchWriter usageEventBatchWriter;

    private final AtomicReference<Session> current = new AtomicReference<>();

    private static final class Session {
        final String tempId;
        volatile int remeasuresUsed;
        volatile byte[] npz;
        volatile String npzSha256;
        volatile Integer screenW;
        volatile Integer screenH;
        volatile Double avgErrorPx;
        volatile Double maxErrorPx;
        volatile String grade;
        volatile Boolean pass;
        volatile String pointsJson;

        Session(String tempId) {
            this.tempId = tempId;
        }
    }

    public CalibrationOrchestrator(AgentHub agentHub, FeHub feHub,
                                   CalibProfileService calibProfileService,
                                   SettingsService settingsService,
                                   UsageEventBatchWriter usageEventBatchWriter) {
        this.agentHub = agentHub;
        this.feHub = feHub;
        this.calibProfileService = calibProfileService;
        this.settingsService = settingsService;
        this.usageEventBatchWriter = usageEventBatchWriter;
    }

    /** FE calib_start — 한도(4개) 검사 후 보정 세션 개시 (재측정 카운트 0). */
    public void start() {
        if (calibProfileService.count() >= CalibProfileService.MAX_PROFILES) {
            feHub.send("calib_denied", Map.of("message",
                    "시선 보정은 최대 " + CalibProfileService.MAX_PROFILES
                            + "개까지 저장할 수 있어요. 사용하지 않는 보정을 삭제한 뒤 다시 시도해 주세요."));
            return;
        }
        String tempId = UUID.randomUUID().toString().substring(0, 8);
        Session old = current.getAndSet(new Session(tempId));
        if (old != null) {
            log.warn("진행 중이던 보정 {} 을 버리고 새 보정 {} 을 시작합니다", old.tempId, tempId);
        }
        agentHub.send("calib_start", Map.of("tempId", tempId));
    }

    /** AI calib_precheck — 위치 확인(얼굴/거리/조명) 상태 중계. */
    public void onPrecheck(JsonNode d) {
        feHub.send("calib_precheck", d != null && d.isObject() ? d : Map.of());
    }

    /**
     * FE calib_point_shown {n, x, y} — AI 에 점 n 수집 시작 신호.
     * 좌표는 점을 실제로 그린 FE 가 정한다 (화면 3×3 중 n 번째 칸의 중앙점). AI 는 이 좌표를 기준점으로
     * 삼아 dx, dy 를 낸다 — 멀티 모니터에서는 좌표가 음수일 수 있고 DPI 배율도 걸리므로 BE·AI 가
     * 해상도만으로 되짚을 수 없다. 그린 쪽이 알려주는 게 유일하게 안전하다.
     */
    public void onPointShown(int n, Integer x, Integer y) {
        if (x == null || y == null) {
            log.warn("점 {} 의 표시 좌표가 없다 — AI 가 오차 기준점을 알 수 없다", n);
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("n", n);
        body.put("x", x);
        body.put("y", y);
        agentHub.send("calib_collect_start", body);
    }

    /** AI calib_point_ready {n, total} — FE 점 표시 지시 (페이로드 그대로. 좌표는 FE 가 정한다). */
    public void onPointReady(JsonNode d) {
        feHub.send("calib_point", d != null && d.isObject() ? d : Map.of());
    }

    /** AI 의 calib.npz 업로드 (PUT /api/agent/calibs/{tempId}/npz, X-Screen 필수). */
    public void attachNpz(String tempId, byte[] payload, int screenW, int screenH) {
        Session session = requireSession(tempId);
        if (payload == null || payload.length < 1 || payload.length > MAX_UPLOAD_BYTES) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "업로드 크기는 1바이트 이상 5MB 이하여야 합니다");
        }
        session.npz = payload;
        session.npzSha256 = Sha256.hex(payload);
        session.screenW = screenW;
        session.screenH = screenH;
    }

    /**
     * AI calib_result — 시선 학습 결과. AI 판정(grade·pass)과 재측정 잔여 횟수를 붙여 FE 로 중계하고
     * 통계(usage_event, kind=calibration)로도 남긴다 — "보정 정확도 저장" 확정 사항.
     * points 는 [{n, dx, dy}] — 목표점을 원점으로 둔 오차 벡터다. BE 는 해석하지 않고 그대로 넘긴다.
     */
    public void onResult(String tempId, JsonNode d) {
        Session session = current.get();
        if (session == null || !session.tempId.equals(tempId)) {
            log.debug("모르는 보정 {} 의 calib_result 무시", tempId);
            return;
        }
        session.avgErrorPx = d.hasNonNull("avgErrorPx") ? d.path("avgErrorPx").asDouble() : null;
        session.maxErrorPx = d.hasNonNull("maxErrorPx") ? d.path("maxErrorPx").asDouble() : null;
        session.grade = d.hasNonNull("grade") ? d.path("grade").asText() : null;
        session.pass = d.hasNonNull("pass") ? d.path("pass").asBoolean() : null;
        session.pointsJson = d.has("points") ? d.path("points").toString() : null;

        Map<String, Object> body = new LinkedHashMap<>();
        body.put("avgErrorPx", session.avgErrorPx);
        body.put("maxErrorPx", session.maxErrorPx);
        body.put("points", d.path("points"));
        body.put("grade", session.grade);
        body.put("pass", session.pass);
        body.put("remeasuresUsed", session.remeasuresUsed);
        body.put("remeasuresLeft", MAX_REMEASURES - session.remeasuresUsed);
        feHub.send("calib_result", body);

        try {
            Map<String, Object> event = new LinkedHashMap<>();
            event.put("eventUid", UUID.randomUUID().toString());
            event.put("kind", "calibration");
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("avgErrorPx", session.avgErrorPx);
            payload.put("maxErrorPx", session.maxErrorPx);
            payload.put("grade", session.grade);
            payload.put("remeasuresUsed", session.remeasuresUsed);
            event.put("payload", payload);
            usageEventBatchWriter.write(List.of(event));
        } catch (Exception e) {
            log.warn("calibration 통계 기록 실패", e);
        }
    }

    /**
     * FE calib_restart — "다시 측정". ★ 세션당 최대 3회, 여기서 센다.
     * 한도를 넘으면 AI 에 아무것도 보내지 않고 FE 에 calib_limit 를 회신한다.
     */
    public void restart() {
        Session session = current.get();
        if (session == null) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "진행 중인 시선 보정이 없습니다");
        }
        if (session.remeasuresUsed >= MAX_REMEASURES) {
            feHub.send("calib_limit", Map.of(
                    "message", "재측정은 최대 " + MAX_REMEASURES + "회까지 할 수 있어요. 지금 결과로 완료하거나 그만둘 수 있습니다.",
                    "remeasuresUsed", session.remeasuresUsed));
            return;
        }
        session.remeasuresUsed++;
        session.avgErrorPx = null;
        session.maxErrorPx = null;
        session.grade = null;
        session.pass = null;
        session.pointsJson = null;
        session.npz = null;
        agentHub.send("calib_restart", Map.of("tempId", session.tempId));
    }

    /**
     * FE calib_commit {name?, deviceLabel?} — "완료". 프로필 확정 저장.
     * 카메라 이름은 <b>OS 가 보고한 장치 이름</b>이고 장비 교체 자동 맵핑의 키가 된다.
     * FE 가 보낸 `deviceLabel`(실제 사용 장치)이 우선, 없으면 설정 `cameraDevice` —
     * 설정이 null(= 시스템 기본)이면 실명을 아는 쪽은 장치를 연 FE 다.
     */
    public void commit(String nameOrNull, String deviceLabelOrNull) {
        Session session = current.get();
        if (session == null) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "진행 중인 시선 보정이 없습니다");
        }
        if (session.npz == null || session.avgErrorPx == null) {
            throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "보정 결과가 아직 도착하지 않았습니다. 잠시 후 다시 시도해 주세요");
        }
        String deviceLabel = (deviceLabelOrNull != null && !deviceLabelOrNull.isBlank())
                ? deviceLabelOrNull.trim()
                : settingsService.peekString("cameraDevice");
        if (deviceLabel == null) {
            log.warn("보정 {} — 카메라 이름을 알 수 없어 장비 라벨 없이 저장합니다"
                    + " (장비 교체 자동 맵핑 대상에서 빠진다)", session.tempId);
        }
        long id = calibProfileService.saveNew(nameOrNull, session.npz, session.npzSha256,
                session.screenW, session.screenH, session.avgErrorPx, session.maxErrorPx,
                session.grade, session.pointsJson, deviceLabel);
        boolean active = orZero(calibProfileService.activeIdOrNull()) == id;

        Map<String, Object> saved = new LinkedHashMap<>();
        saved.put("id", id);
        saved.put("name", nameOf(id));
        saved.put("avgErrorPx", session.avgErrorPx);
        saved.put("active", active);
        feHub.send("calib_saved", saved);
        agentHub.send("calib_registered", Map.of("id", id, "active", active));
        current.compareAndSet(session, null);
    }

    /** FE calib_cancel — "그만두기". 측정 데이터 폐기, 이전 보정 유지. */
    public void cancel() {
        Session session = current.getAndSet(null);
        if (session != null) {
            agentHub.send("calib_cancel", Map.of("tempId", session.tempId));
        }
    }

    // ------------------------------------------------------------------ 내부

    private Session requireSession(String tempId) {
        Session session = current.get();
        if (session == null || !session.tempId.equals(tempId)) {
            throw new ApiException(ErrorCode.PROFILE_NOT_FOUND, "진행 중인 시선 보정이 없습니다: " + tempId);
        }
        return session;
    }

    private String nameOf(long id) {
        try {
            return (String) calibProfileService.get(id).get("name");
        } catch (Exception e) {
            return null;
        }
    }

    private static long orZero(Long v) {
        return v == null ? 0 : v;
    }
}
