package com.sia.assistant.settings;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.Times;
import com.sia.assistant.config.DataDirs;
import com.sia.assistant.relay.AgentSyncNotifier;
import com.sia.assistant.ws.AgentHub;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.ObjectMapper;

/**
 * gesture / gesture_step 이 매핑의 원천이다 (설정 JSON 의 투영이 아니다).
 * 커스텀 제스처는 kind=HAND, custom=1 이고 템플릿 npz 를 같은 행에 갖는다 — 제스처별 npz 1개 (흐름도 03).
 * ★2026-09-02: 옛 blob 'gestures_custom'(전체 템플릿 한 파일)을 버렸다. AI 는 gesture_registered {id, sha256} 를
 *   받아 GET /api/agent/gestures/{id}/npz 로 내려받고, 이름 변경·삭제에는 npz 를 다시 올리지 않는다.
 * 와이어프레임 확정(2026-09-01) 반영: 켜기/끄기(enabled)·등록일(created_at)·등록 영상(video_path)·
 * 목록 페이지네이션·수정(이름/기능)·매크로 최대 5단계.
 */
@Service
public class GestureService {

    public record Step(String tool, Map<String, Object> args, Integer delayMs) {
    }

    public record GestureDef(long id, String kind, String context, String name, String label,
                             boolean repeatable, boolean enabled, boolean custom, List<Step> steps) {
    }

    public record Page(int page, int pageSize, int total, List<Map<String, Object>> items) {
    }

    /** 템플릿 npz 메타 — GET /api/agent/gestures/{id}/npz 의 ETag 재료. */
    public record NpzMeta(long id, String name, String sha256, long bytes) {
    }

    /** 매크로 단계 상한 — 와이어프레임 등록 화면 "최대 5개". */
    public static final int MAX_STEPS = 5;
    /** 템플릿 npz 크기 — blob(wakeword)·보정 npz 와 같은 1B ~ 5MB. */
    public static final int NPZ_MIN_BYTES = 1;
    public static final int NPZ_MAX_BYTES = 5 * 1024 * 1024;

    private static final Logger log = LoggerFactory.getLogger(GestureService.class);

    /** requireRow 결과 — 기본/커스텀 판정과 AI 통지에 필요한 최소 필드. */
    private record Row(long id, boolean custom, String kind, String context, String name, String videoPath) {
    }

    private final JdbcTemplate jdbc;
    private final ObjectMapper om;
    private final AgentHub agentHub;
    private final DataDirs dataDirs;
    /** 켜기/끄기는 disabledGestures 를 바꾼다 — settings_changed 도 함께 나간다. 순환은 지연 조회로 끊는다. */
    private final ObjectProvider<AgentSyncNotifier> notifierProvider;

    public GestureService(JdbcTemplate jdbc, ObjectMapper om, AgentHub agentHub, DataDirs dataDirs,
                          ObjectProvider<AgentSyncNotifier> notifierProvider) {
        this.jdbc = jdbc;
        this.om = om;
        this.agentHub = agentHub;
        this.dataDirs = dataDirs;
        this.notifierProvider = notifierProvider;
    }

    /**
     * 매핑 목록 (단계 포함) — ★페이지네이션 (FE 로딩 성능, 회의 확정).
     * runnable = 모든 스텝의 tool 이 이번 기동에 등록(available=1)됐는가.
     * custom 컬럼으로 기본/커스텀을 나눠 불러올 수 있다 (와이어프레임의 두 섹션).
     */
    public Page list(String kindOrNull, Boolean customOrNull, Integer handsOrNull, String motionOrNull,
                     boolean danglingOnly, int page, int size) {
        int pageSize = Math.min(Math.max(size, 1), 100);
        int safePage = Math.max(page, 0);

        StringBuilder where = new StringBuilder(" WHERE 1=1");
        List<Object> params = new ArrayList<>();
        if (kindOrNull != null && !kindOrNull.isBlank()) {
            where.append(" AND kind = ?");
            params.add(kindOrNull);
        }
        if (customOrNull != null) {
            where.append(customOrNull ? " AND custom = 1" : " AND custom = 0");
        }
        if (handsOrNull != null) {
            where.append(" AND hands = ?");
            params.add(requireHands(handsOrNull));
        }
        if (motionOrNull != null && !motionOrNull.isBlank()) {
            where.append(" AND motion = ?");
            params.add(requireMotion(motionOrNull));
        }

        List<Map<String, Object>> gestures = jdbc.query(
                "SELECT id, custom, kind, context, name, label, description, repeatable,"
                        + " enabled, created_at, video_path, hands, motion FROM gesture" + where
                        + " ORDER BY id",
                (rs, i) -> {
                    Map<String, Object> g = new LinkedHashMap<>();
                    long id = rs.getLong("id");
                    g.put("id", id);
                    g.put("kind", rs.getString("kind"));
                    g.put("hands", rs.getObject("hands") == null ? null : rs.getInt("hands"));
                    g.put("motion", rs.getString("motion"));
                    g.put("context", rs.getString("context"));
                    g.put("name", rs.getString("name"));
                    g.put("label", rs.getString("label"));
                    g.put("description", rs.getString("description"));
                    g.put("repeatable", rs.getInt("repeatable") == 1);
                    g.put("enabled", rs.getInt("enabled") == 1);
                    g.put("custom", rs.getInt("custom") == 1);
                    g.put("createdAt", rs.getString("created_at"));
                    g.put("videoUrl", rs.getString("video_path") == null ? null : "/api/gestures/" + id + "/video");
                    return g;
                }, params.toArray());

        // 스텝 + 도구 가용성 일괄 조회 후 메모리 조립 (N+1 회피)
        Map<Long, List<Map<String, Object>>> stepsById = new LinkedHashMap<>();
        Map<Long, Boolean> runnableById = new LinkedHashMap<>();
        jdbc.query("SELECT gs.gesture_id, gs.step_no, gs.tool_name, gs.args_json, gs.delay_ms, t.available"
                + " FROM gesture_step gs JOIN tool t ON t.name = gs.tool_name"
                + " ORDER BY gs.gesture_id, gs.step_no", rs -> {
            long gestureId = rs.getLong("gesture_id");
            Map<String, Object> step = new LinkedHashMap<>();
            step.put("tool", rs.getString("tool_name"));
            step.put("args", parseArgs(rs.getString("args_json")));
            step.put("delayMs", rs.getObject("delay_ms") == null ? null : rs.getInt("delay_ms"));
            boolean available = rs.getInt("available") == 1;
            step.put("available", available);
            stepsById.computeIfAbsent(gestureId, k -> new ArrayList<>()).add(step);
            runnableById.merge(gestureId, available, Boolean::logicalAnd);
        });

        List<Map<String, Object>> filtered = new ArrayList<>();
        for (Map<String, Object> g : gestures) {
            long id = (Long) g.get("id");
            boolean runnable = runnableById.getOrDefault(id, false);
            g.put("runnable", runnable);
            g.put("steps", stepsById.getOrDefault(id, List.of()));
            if (!danglingOnly || !runnable) {
                filtered.add(g);
            }
        }

        int total = filtered.size();
        int from = Math.min(safePage * pageSize, total);
        int to = Math.min(from + pageSize, total);
        return new Page(safePage, pageSize, total, filtered.subList(from, to));
    }

    /** 단건 조회 (FE 상세·수정 화면). */
    public Map<String, Object> getOne(long id) {
        List<Map<String, Object>> rows = jdbc.query(
                "SELECT id, custom, kind, context, name, label, description, repeatable,"
                        + " enabled, created_at, video_path, hands, motion FROM gesture WHERE id = ?",
                (rs, i) -> {
                    Map<String, Object> g = new LinkedHashMap<>();
                    g.put("id", rs.getLong("id"));
                    g.put("kind", rs.getString("kind"));
                    g.put("hands", rs.getObject("hands") == null ? null : rs.getInt("hands"));
                    g.put("motion", rs.getString("motion"));
                    g.put("context", rs.getString("context"));
                    g.put("name", rs.getString("name"));
                    g.put("label", rs.getString("label"));
                    g.put("description", rs.getString("description"));
                    g.put("repeatable", rs.getInt("repeatable") == 1);
                    g.put("enabled", rs.getInt("enabled") == 1);
                    g.put("custom", rs.getInt("custom") == 1);
                    g.put("createdAt", rs.getString("created_at"));
                    g.put("videoUrl", rs.getString("video_path") == null
                            ? null : "/api/gestures/" + rs.getLong("id") + "/video");
                    return g;
                }, id);
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.GESTURE_NOT_FOUND, "해당 제스처가 없습니다: " + id);
        }
        Map<String, Object> g = rows.get(0);
        List<Map<String, Object>> steps = jdbc.query(
                "SELECT gs.tool_name, gs.args_json, gs.delay_ms, t.available FROM gesture_step gs"
                        + " JOIN tool t ON t.name = gs.tool_name WHERE gs.gesture_id = ? ORDER BY gs.step_no",
                (rs, i) -> {
                    Map<String, Object> step = new LinkedHashMap<>();
                    step.put("tool", rs.getString("tool_name"));
                    step.put("args", parseArgs(rs.getString("args_json")));
                    step.put("delayMs", rs.getObject("delay_ms") == null ? null : rs.getInt("delay_ms"));
                    step.put("available", rs.getInt("available") == 1);
                    return step;
                }, id);
        g.put("steps", steps);
        g.put("runnable", !steps.isEmpty()
                && steps.stream().allMatch(s -> Boolean.TRUE.equals(s.get("available"))));
        return g;
    }

    /** 꺼진 제스처 이름 목록 — recognition_start / settings_changed 의 disabledGestures. */
    public List<String> disabledNames() {
        return jdbc.query("SELECT DISTINCT name FROM gesture WHERE enabled = 0 ORDER BY name",
                (rs, i) -> rs.getString(1));
    }

    // ------------------------------------------------------------------ 템플릿 npz (제스처별)

    /**
     * blobs.gestures — 템플릿을 가진 커스텀 제스처 전부 [{id, name, sha256, hands, motion}], id 순.
     * hello_ack · recognition_start · settings_changed 에 실리고, AI 는 sha256 이 다른 것만 다시 내려받는다.
     * hands · motion 도 함께 내려 준다 — AI 가 내려받은 npz 의 배열 모양을 역산해 분류를 복원하지 않게 한다.
     */
    public List<Map<String, Object>> customNpzRefs() {
        return jdbc.query(
                "SELECT id, name, npz_sha256, hands, motion FROM gesture"
                        + " WHERE custom = 1 AND npz IS NOT NULL ORDER BY id",
                (rs, i) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", rs.getLong("id"));
                    m.put("name", rs.getString("name"));
                    m.put("sha256", rs.getString("npz_sha256"));
                    m.put("hands", rs.getObject("hands") == null ? null : rs.getInt("hands"));
                    m.put("motion", rs.getString("motion"));
                    return m;
                });
    }

    /** 템플릿 메타 — 행이 없으면 GESTURE_NOT_FOUND, 템플릿이 없으면(기본 제공) BLOB_NOT_FOUND. */
    public NpzMeta npzMeta(long id) {
        List<NpzMeta> rows = jdbc.query(
                "SELECT id, name, npz_sha256, npz_bytes FROM gesture WHERE id = ?",
                (rs, i) -> new NpzMeta(rs.getLong("id"), rs.getString("name"), rs.getString("npz_sha256"),
                        rs.getObject("npz_bytes") == null ? 0L : rs.getLong("npz_bytes")), id);
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.GESTURE_NOT_FOUND, "해당 제스처가 없습니다: " + id);
        }
        if (rows.get(0).sha256() == null) {
            throw new ApiException(ErrorCode.BLOB_NOT_FOUND, "저장된 제스처 템플릿이 없습니다: " + id);
        }
        return rows.get(0);
    }

    /** 템플릿 npz 원본 — GET /api/agent/gestures/{id}/npz (AI 캐시) · GET /api/gestures/{id}/npz (백업). */
    public byte[] npz(long id) {
        List<byte[]> rows = jdbc.query("SELECT npz FROM gesture WHERE id = ? AND npz IS NOT NULL",
                (rs, i) -> rs.getBytes("npz"), id);
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.BLOB_NOT_FOUND, "저장된 제스처 템플릿이 없습니다: " + id);
        }
        return rows.get(0);
    }

    /**
     * 동작 재촬영(reg_start {replaceGestureId})의 템플릿 교체. 기본 제공 제스처에는 쓸 수 없다.
     * 형태(hands · motion)도 함께 바꾼다 — 한손 정적으로 등록한 제스처를 양손 동적으로 다시 찍을 수 있다.
     */
    public void updateNpz(long id, byte[] npz, String npzSha256, Integer hands, String motion) {
        Row row = requireRow(id);
        if (!row.custom()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "기본 제공 제스처에는 템플릿을 넣을 수 없습니다");
        }
        if (npz == null || npz.length == 0) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "제스처 템플릿(npz)이 필요합니다");
        }
        jdbc.update("UPDATE gesture SET npz = ?, npz_sha256 = ?, npz_bytes = ?, hands = ?, motion = ?"
                        + " WHERE id = ?",
                npz, npzSha256, npz.length, hands == null ? null : requireHands(hands),
                motion == null ? null : requireMotion(motion), id);
    }

    // ------------------------------------------------------------------ 실행용 조회

    /**
     * 실행용 조회 — contextChain 순서대로 context 일치(kind 무관)를 찾고, 마지막에 context IS NULL 을 시도한다.
     */
    public Optional<GestureDef> find(String name, List<String> contextChain) {
        if (contextChain != null) {
            for (String ctx : contextChain) {
                if (ctx == null || ctx.isBlank()) {
                    continue;
                }
                Optional<GestureDef> hit = findOne(name, ctx);
                if (hit.isPresent()) {
                    return hit;
                }
            }
        }
        return findOne(name, null);
    }

    // ------------------------------------------------------------------ 변경

    /**
     * 커스텀 제스처 upsert (kind=HAND 고정, UNIQUE(kind,context,name) 기준) + 스텝 전체 재작성 + 템플릿 npz 저장. 한 트랜잭션.
     * npz 는 필수다 — 등록 중 AI 가 PUT /api/agent/gestures/{tempId}/npz 로 올린 임시본을 RegistrationOrchestrator 가 넘긴다.
     * 같은 이름의 기본 제공 제스처가 있으면 거절한다 (AI 가 이름으로 gesture_exec 를 보내므로 겹치면 안 된다).
     *
     * @return 저장된 gesture id
     */
    @Transactional
    public long saveCustom(String name, String label, String context, String description,
                           boolean repeatable, List<Step> steps, byte[] npz, String npzSha256,
                           Integer hands, String motion) {
        if (name == null || name.isBlank()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "제스처 이름이 필요합니다");
        }
        if (npz == null || npz.length == 0) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "제스처 템플릿(npz)이 필요합니다");
        }
        String ctx = (context == null || context.isBlank()) ? null : context;
        Integer safeHands = hands == null ? null : requireHands(hands);
        String safeMotion = motion == null ? null : requireMotion(motion);
        validateSteps(steps);

        // SQLite 의 UNIQUE 는 NULL 끼리 충돌하지 않아 ON CONFLICT 를 못 쓴다 — 직접 조회 후 분기
        Long id = findGestureId("HAND", ctx, name);
        if (id == null) {
            jdbc.update("INSERT INTO gesture (custom, kind, context, name, label, description,"
                            + " repeatable, enabled, created_at, npz, npz_sha256, npz_bytes, hands, motion)"
                            + " VALUES (1, 'HAND', ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?)",
                    ctx, name, label, description, repeatable ? 1 : 0, Times.now(), npz, npzSha256, npz.length,
                    safeHands, safeMotion);
            id = jdbc.queryForObject("SELECT last_insert_rowid()", Long.class);
        } else {
            if (!requireRow(id).custom()) {
                throw new ApiException(ErrorCode.INVALID_REQUEST, "기본 제공 제스처와 같은 이름은 쓸 수 없어요: " + name);
            }
            jdbc.update("UPDATE gesture SET label = ?, description = ?, repeatable = ?,"
                            + " npz = ?, npz_sha256 = ?, npz_bytes = ?, hands = ?, motion = ? WHERE id = ?",
                    label, description, repeatable ? 1 : 0, npz, npzSha256, npz.length,
                    safeHands, safeMotion, id);
            jdbc.update("DELETE FROM gesture_step WHERE gesture_id = ?", id);
        }
        writeSteps(id, steps);
        return id;
    }

    /** 등록(또는 재촬영) 영상 파일명 기록 — 파일 이동은 RegistrationOrchestrator 가 한다. */
    public void setVideoPath(long id, String fileName) {
        jdbc.update("UPDATE gesture SET video_path = ? WHERE id = ?", fileName, id);
    }

    public String videoPath(long id) {
        List<String> rows = jdbc.query("SELECT video_path FROM gesture WHERE id = ?",
                (rs, i) -> rs.getString(1), id);
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.GESTURE_NOT_FOUND, "해당 제스처가 없습니다: " + id);
        }
        return rows.get(0);
    }

    /**
     * 커스텀 제스처 수정 (와이어프레임 제스처 수정 화면) — 이름·라벨·설명·반복·기능(스텝).
     * 이름이 바뀌면 AI 에 gesture_renamed {id, oldName, newName} 를 보낸다 — 템플릿은 id 로 내려받으므로
     * AI 는 이름표만 바꾸고 npz 를 다시 올리지 않는다.
     * 영상 재촬영은 여기가 아니라 WS reg_start {replaceGestureId} 경로다.
     */
    @Transactional
    public void updateCustom(long id, String nameOrNull, String labelOrNull, String descriptionOrNull,
                             Boolean repeatableOrNull, List<Step> stepsOrNull) {
        Row row = requireRow(id);
        if (!row.custom()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "기본 제공 제스처는 켜기/끄기만 가능합니다");
        }
        String oldName = row.name();
        String ctx = row.context();

        if (nameOrNull != null && !nameOrNull.isBlank() && !nameOrNull.equals(oldName)) {
            Long clash = findGestureId(row.kind(), ctx, nameOrNull);
            if (clash != null && clash != id) {
                throw new ApiException(ErrorCode.INVALID_REQUEST, "이미 같은 이름의 제스처가 있어요");
            }
            jdbc.update("UPDATE gesture SET name = ? WHERE id = ?", nameOrNull, id);
            Map<String, Object> renamed = new LinkedHashMap<>();
            renamed.put("id", id);
            renamed.put("oldName", oldName);
            renamed.put("newName", nameOrNull);
            agentHub.send("gesture_renamed", renamed);
        }
        if (labelOrNull != null) {
            jdbc.update("UPDATE gesture SET label = ? WHERE id = ?", labelOrNull, id);
        }
        if (descriptionOrNull != null) {
            jdbc.update("UPDATE gesture SET description = ? WHERE id = ?", descriptionOrNull, id);
        }
        if (repeatableOrNull != null) {
            jdbc.update("UPDATE gesture SET repeatable = ? WHERE id = ?", repeatableOrNull ? 1 : 0, id);
        }
        if (stepsOrNull != null) {
            validateSteps(stepsOrNull);
            jdbc.update("DELETE FROM gesture_step WHERE gesture_id = ?", id);
            writeSteps(id, stepsOrNull);
        }
    }

    /**
     * 켜기/끄기 (기본 제스처 포함 — "기본 제공 제스처는 켜기/끄기만 가능합니다").
     * AI 에 gesture_toggled 를 보낸다 — 꺼진 제스처는 감지에서 제외되고, BE 실행도 막힌다.
     * 이어서 settings_changed 로 전체 상태를 다시 실어 보낸다 — AI 가 settings_changed 하나만 듣고 있어도
     * 토글을 놓치지 않게 하는 계약이다 (프로토콜 §4.2).
     */
    public void setEnabled(long id, boolean enabled) {
        Row row = requireRow(id);
        jdbc.update("UPDATE gesture SET enabled = ? WHERE id = ?", enabled ? 1 : 0, id);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("name", row.name());
        body.put("context", row.context());
        body.put("enabled", enabled);
        agentHub.send("gesture_toggled", body);
        AgentSyncNotifier notifier = notifierProvider.getIfAvailable();
        if (notifier != null) {
            notifier.notifySettingsChanged();
        }
    }

    /**
     * 커스텀 제스처 삭제 (id 기준). 기본 매핑(custom=0)은 지울 수 없다.
     * 템플릿 npz 는 행과 함께 사라지고 등록 영상 파일도 지운다. AI 에는 gesture_removed {id, name} 만 간다.
     */
    @Transactional
    public void removeCustom(long id) {
        Row row = requireRow(id);
        if (!row.custom()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "기본 제공 매핑은 삭제할 수 없습니다");
        }
        jdbc.update("DELETE FROM gesture WHERE id = ?", id); // gesture_step 은 ON DELETE CASCADE
        deleteVideoFile(row.videoPath());
        Map<String, Object> removed = new LinkedHashMap<>();
        removed.put("id", id);
        removed.put("name", row.name());
        agentHub.send("gesture_removed", removed);
    }

    /** 전체 삭제(WipeService)용 — 등록 영상 파일 일괄 제거. */
    public void deleteAllVideos() {
        try (var files = Files.list(dataDirs.gestures())) {
            files.forEach(p -> {
                try {
                    Files.deleteIfExists(p);
                } catch (Exception e) {
                    log.warn("제스처 영상 삭제 실패: {}", p, e);
                }
            });
        } catch (Exception e) {
            log.warn("제스처 영상 폴더 정리 실패", e);
        }
    }

    // ------------------------------------------------------------------ 내부

    private void writeSteps(long id, List<Step> steps) {
        int no = 1;
        for (Step step : steps) {
            jdbc.update("INSERT INTO gesture_step (gesture_id, tool_name, step_no, args_json, delay_ms)"
                            + " VALUES (?, ?, ?, ?, ?)",
                    id, step.tool(), no++, serializeArgs(step.args()), step.delayMs());
        }
    }

    private void validateSteps(List<Step> steps) {
        if (steps == null || steps.isEmpty()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "매크로에는 최소 한 단계가 필요합니다");
        }
        if (steps.size() > MAX_STEPS) {
            throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "매크로 단계는 최대 " + MAX_STEPS + "개까지 쌓을 수 있습니다");
        }
        for (Step step : steps) {
            if (step.tool() == null || step.tool().isBlank()) {
                throw new ApiException(ErrorCode.INVALID_REQUEST, "각 단계에는 tool 이 필요합니다");
            }
            List<Integer> confirm = jdbc.query("SELECT confirm_required FROM tool WHERE name = ?",
                    (rs, n) -> rs.getInt(1), step.tool());
            if (confirm.isEmpty()) {
                throw new ApiException(ErrorCode.INVALID_REQUEST, "등록되지 않은 도구입니다: " + step.tool());
            }
            // ★ C 도구는 매크로에 아예 넣을 수 없다. C 의 뜻이 "AI 가 호출 전 사용자 동의를 받는다"인데
            //   제스처 경로에는 AI 판단이 없어 그 정책을 만족시킬 방법이 없다.
            //   와이어프레임의 기능 선택 드롭다운도 "파일 삭제 · 제스처로 실행 불가"로 막아 두었다.
            if (confirm.get(0) == 1) {
                throw new ApiException(ErrorCode.INVALID_REQUEST,
                        "사용자 동의가 필요한 도구는 제스처로 실행할 수 없습니다: " + step.tool());
            }
        }
    }

    private Row requireRow(long id) {
        List<Row> rows = jdbc.query(
                "SELECT id, custom, kind, context, name, video_path FROM gesture WHERE id = ?",
                (rs, i) -> new Row(rs.getLong("id"), rs.getInt("custom") == 1, rs.getString("kind"),
                        rs.getString("context"), rs.getString("name"), rs.getString("video_path")), id);
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.GESTURE_NOT_FOUND, "해당 제스처가 없습니다: " + id);
        }
        return rows.get(0);
    }

    private void deleteVideoFile(String fileName) {
        if (fileName == null || fileName.isBlank()) {
            return;
        }
        try {
            Files.deleteIfExists(dataDirs.gestures().resolve(fileName));
        } catch (Exception e) {
            log.warn("제스처 영상 삭제 실패: {}", fileName, e);
        }
    }

    /**
     * hands · motion 값 검증. SQLite 의 ALTER TABLE ... ADD COLUMN 은 CHECK 를 받지 않아
     * V3 마이그레이션이 제약을 걸 수 없다 — 두 축의 유일한 문지기가 여기다.
     */
    public static int requireHands(int hands) {
        if (hands != 1 && hands != 2) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "hands 는 1 또는 2 여야 합니다");
        }
        return hands;
    }

    public static String requireMotion(String motion) {
        String up = motion == null ? "" : motion.trim().toUpperCase(Locale.ROOT);
        if (!up.equals("STATIC") && !up.equals("DYNAMIC")) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "motion 은 STATIC 또는 DYNAMIC 이어야 합니다");
        }
        return up;
    }

    private Long findGestureId(String kind, String ctx, String name) {
        String sql = ctx == null
                ? "SELECT id FROM gesture WHERE kind = ? AND name = ? AND context IS NULL"
                : "SELECT id FROM gesture WHERE kind = ? AND name = ? AND context = ?";
        Object[] params = ctx == null ? new Object[]{kind, name} : new Object[]{kind, name, ctx};
        List<Long> ids = jdbc.query(sql, (rs, i) -> rs.getLong(1), params);
        return ids.isEmpty() ? null : ids.get(0);
    }

    private Optional<GestureDef> findOne(String name, String ctx) {
        String sql = ctx == null
                ? "SELECT id, custom, kind, context, name, label, repeatable, enabled FROM gesture"
                        + " WHERE name = ? AND context IS NULL ORDER BY id LIMIT 1"
                : "SELECT id, custom, kind, context, name, label, repeatable, enabled FROM gesture"
                        + " WHERE name = ? AND context = ? ORDER BY id LIMIT 1";
        Object[] params = ctx == null ? new Object[]{name} : new Object[]{name, ctx};
        List<GestureDef> heads = jdbc.query(sql, (rs, i) -> new GestureDef(
                rs.getLong("id"),
                rs.getString("kind"),
                rs.getString("context"),
                rs.getString("name"),
                rs.getString("label"),
                rs.getInt("repeatable") == 1,
                rs.getInt("enabled") == 1,
                rs.getInt("custom") == 1,
                List.of()), params);
        if (heads.isEmpty()) {
            return Optional.empty();
        }
        GestureDef head = heads.get(0);
        List<Step> steps = jdbc.query(
                "SELECT tool_name, args_json, delay_ms FROM gesture_step WHERE gesture_id = ? ORDER BY step_no",
                (rs, i) -> new Step(
                        rs.getString("tool_name"),
                        parseArgs(rs.getString("args_json")),
                        rs.getObject("delay_ms") == null ? null : rs.getInt("delay_ms")),
                head.id());
        return Optional.of(new GestureDef(head.id(), head.kind(), head.context(), head.name(),
                head.label(), head.repeatable(), head.enabled(), head.custom(), steps));
    }

    private Map<String, Object> parseArgs(String argsJson) {
        if (argsJson == null || argsJson.isBlank()) {
            return Map.of();
        }
        try {
            return om.readValue(argsJson, new TypeReference<Map<String, Object>>() {
            });
        } catch (Exception e) {
            log.warn("args_json 파싱 실패 — 빈 인자로 대체합니다: {}", argsJson);
            return Map.of();
        }
    }

    private String serializeArgs(Map<String, Object> args) {
        if (args == null || args.isEmpty()) {
            return "{}";
        }
        try {
            return om.writeValueAsString(args);
        } catch (Exception e) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "단계 인자를 저장할 수 없는 형식입니다");
        }
    }
}
