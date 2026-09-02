package com.sia.assistant.profile;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.Times;
import com.sia.assistant.ws.AgentHub;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/**
 * 시선 보정 프로필 저장소 — 최대 4개 (사용 1 + 스톡 3), 와이어프레임 시선 섹션의 원천.
 * 보정 정확도(평균/최대 오차)와 시선 학습 결과 산점도(points_json), 학습 해상도를 함께 저장한다.
 * 보정 진행 중 임시본은 CalibrationOrchestrator 메모리에 있고, 여기는 확정본만 다룬다.
 */
@Service
public class CalibProfileService {

    public static final int MAX_PROFILES = 4;
    /** 통과 기준 — 평균 오차 50px 이하 (와이어프레임 "기준 50px 이하"). */
    public static final double THRESHOLD_PX = 50.0;

    private final JdbcTemplate jdbc;
    private final AgentHub agentHub;

    public CalibProfileService(JdbcTemplate jdbc, AgentHub agentHub) {
        this.jdbc = jdbc;
        this.agentHub = agentHub;
    }

    // ------------------------------------------------------------------ 조회

    /** AI blobs 페이로드의 calib 항목 — {id, sha256, screenW, screenH} 또는 null. */
    public Map<String, Object> activeRefOrNull() {
        List<Map<String, Object>> rows = jdbc.query(
                "SELECT id, npz_sha256, screen_w, screen_h FROM calib_profile WHERE active = 1 LIMIT 1",
                (rs, i) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", rs.getLong("id"));
                    m.put("sha256", rs.getString("npz_sha256"));
                    m.put("screenW", rs.getObject("screen_w") == null ? null : rs.getInt("screen_w"));
                    m.put("screenH", rs.getObject("screen_h") == null ? null : rs.getInt("screen_h"));
                    return m;
                });
        return rows.isEmpty() ? null : rows.get(0);
    }

    public Long activeIdOrNull() {
        List<Long> ids = jdbc.query("SELECT id FROM calib_profile WHERE active = 1 LIMIT 1",
                (rs, i) -> rs.getLong(1));
        return ids.isEmpty() ? null : ids.get(0);
    }

    public int count() {
        Integer n = jdbc.queryForObject("SELECT COUNT(*) FROM calib_profile", Integer.class);
        return n == null ? 0 : n;
    }

    /** FE 목록 — 사용 중이 먼저, 그다음 등록일 순. 산점도는 상세(get)에서만 준다. */
    public List<Map<String, Object>> list() {
        return jdbc.query(
                "SELECT id, name, active, device_label, screen_w, screen_h,"
                        + " avg_error_px, max_error_px, created_at, last_used_at FROM calib_profile"
                        + " ORDER BY active DESC, created_at ASC, id ASC",
                (rs, i) -> summaryRow(rs.getLong("id"), rs.getString("name"), rs.getInt("active") == 1,
                        rs.getString("device_label"),
                        rs.getObject("screen_w") == null ? null : rs.getInt("screen_w"),
                        rs.getObject("screen_h") == null ? null : rs.getInt("screen_h"),
                        rs.getObject("avg_error_px") == null ? null : rs.getDouble("avg_error_px"),
                        rs.getObject("max_error_px") == null ? null : rs.getDouble("max_error_px"),
                        rs.getString("created_at"), rs.getString("last_used_at")));
    }

    /** 상세 — 목록 필드 + points(산점도 JSON 원문 문자열). */
    public Map<String, Object> get(long id) {
        List<Map<String, Object>> rows = jdbc.query(
                "SELECT id, name, active, device_label, screen_w, screen_h, avg_error_px, max_error_px,"
                        + " points_json, created_at, last_used_at FROM calib_profile WHERE id = ?",
                (rs, i) -> {
                    Map<String, Object> m = summaryRow(rs.getLong("id"), rs.getString("name"),
                            rs.getInt("active") == 1, rs.getString("device_label"),
                            rs.getObject("screen_w") == null ? null : rs.getInt("screen_w"),
                            rs.getObject("screen_h") == null ? null : rs.getInt("screen_h"),
                            rs.getObject("avg_error_px") == null ? null : rs.getDouble("avg_error_px"),
                            rs.getObject("max_error_px") == null ? null : rs.getDouble("max_error_px"),
                            rs.getString("created_at"), rs.getString("last_used_at"));
                    m.put("pointsJson", rs.getString("points_json"));
                    return m;
                }, id);
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.PROFILE_NOT_FOUND, "해당 보정이 없습니다: " + id);
        }
        return rows.get(0);
    }

    public byte[] npz(long id) {
        List<byte[]> rows = jdbc.query(
                "SELECT npz FROM calib_profile WHERE id = ? AND npz IS NOT NULL",
                (rs, i) -> rs.getBytes("npz"), id);
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.PROFILE_NOT_FOUND, "저장된 보정 데이터가 없습니다");
        }
        return rows.get(0);
    }

    /** 활성 프로필의 npz 메타 — AI 캐시 갱신용. X-Screen 검사는 컨트롤러가 이 값으로 한다. */
    public Map<String, Object> activeNpzMeta() {
        List<Map<String, Object>> rows = jdbc.query(
                "SELECT id, npz_sha256, screen_w, screen_h FROM calib_profile"
                        + " WHERE active = 1 AND npz IS NOT NULL LIMIT 1",
                (rs, i) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", rs.getLong("id"));
                    m.put("sha256", rs.getString("npz_sha256"));
                    m.put("screenW", rs.getObject("screen_w") == null ? null : rs.getInt("screen_w"));
                    m.put("screenH", rs.getObject("screen_h") == null ? null : rs.getInt("screen_h"));
                    return m;
                });
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.PROFILE_NOT_FOUND, "사용 중인 보정이 없습니다");
        }
        return rows.get(0);
    }

    /** 장비 이름으로 후보 조회 — 최근 사용일 내림차순 (자동 맵핑·사용자 질문의 재료). */
    public List<Map<String, Object>> byDevice(String deviceLabel) {
        return jdbc.query(
                "SELECT id, name, active, avg_error_px, created_at, last_used_at FROM calib_profile"
                        + " WHERE device_label = ?"
                        + " ORDER BY COALESCE(last_used_at, created_at) DESC, id DESC",
                (rs, i) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", rs.getLong("id"));
                    m.put("name", rs.getString("name"));
                    m.put("active", rs.getInt("active") == 1);
                    m.put("avgErrorPx", rs.getObject("avg_error_px") == null ? null : rs.getDouble("avg_error_px"));
                    m.put("createdAt", rs.getString("created_at"));
                    m.put("lastUsedAt", rs.getString("last_used_at"));
                    return m;
                }, deviceLabel);
    }

    // ------------------------------------------------------------------ 변경

    /**
     * 보정 확정 — 오케스트레이터가 calib_commit 에서 부른다. 첫 프로필이면 자동 활성 (온보딩).
     *
     * @return 새 프로필 id
     */
    @Transactional
    public long saveNew(String nameOrNull, byte[] npz, String npzSha256, Integer screenW, Integer screenH,
                        Double avgErrorPx, Double maxErrorPx, String pointsJson, String deviceLabel) {
        if (count() >= MAX_PROFILES) {
            throw new ApiException(ErrorCode.PROFILE_LIMIT,
                    "시선 보정은 최대 " + MAX_PROFILES + "개까지 저장할 수 있습니다. 먼저 사용하지 않는 보정을 삭제해 주세요");
        }
        String name = (nameOrNull == null || nameOrNull.isBlank()) ? nextDefaultName() : nameOrNull.trim();
        boolean first = count() == 0;
        String now = Times.now();
        jdbc.update("INSERT INTO calib_profile (name, active, device_label, npz, npz_sha256, npz_bytes,"
                        + " screen_w, screen_h, avg_error_px, max_error_px, points_json, created_at, last_used_at)"
                        + " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                name, first ? 1 : 0, deviceLabel, npz, npzSha256, npz == null ? null : npz.length,
                screenW, screenH, avgErrorPx, maxErrorPx, pointsJson, now, first ? now : null);
        Long id = jdbc.queryForObject("SELECT last_insert_rowid()", Long.class);
        if (first) {
            notifyCalibChanged(id, npzSha256, screenW, screenH);
        }
        return id;
    }

    /** 사용으로 설정 — 이전·새 활성 모두 최근 사용일을 찍고, AI 에 calib_changed 를 보낸다. */
    @Transactional
    public Map<String, Object> activate(long id) {
        Map<String, Object> target = require(id);
        String now = Times.now();
        jdbc.update("UPDATE calib_profile SET active = 0, last_used_at = ? WHERE active = 1", now);
        jdbc.update("UPDATE calib_profile SET active = 1, last_used_at = ? WHERE id = ?", now, id);
        notifyCalibChanged(id, (String) target.get("npzSha256"),
                (Integer) target.get("screenW"), (Integer) target.get("screenH"));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", id);
        out.put("name", target.get("name"));
        return out;
    }

    public void rename(long id, String name) {
        if (name == null || name.isBlank()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "보정 이름이 필요합니다");
        }
        if (jdbc.update("UPDATE calib_profile SET name = ? WHERE id = ?", name.trim(), id) == 0) {
            throw new ApiException(ErrorCode.PROFILE_NOT_FOUND, "해당 보정이 없습니다: " + id);
        }
    }

    /** 완전 삭제 — 사용 중이거나 마지막 1개면 거부 (와이어프레임 삭제 규칙 그대로). */
    @Transactional
    public void delete(long id) {
        Map<String, Object> target = require(id);
        if (Boolean.TRUE.equals(target.get("active"))) {
            throw new ApiException(ErrorCode.PROFILE_IN_USE,
                    "사용 중인 보정은 삭제할 수 없습니다. 먼저 다른 보정을 사용으로 설정해 주세요");
        }
        if (count() <= 1) {
            throw new ApiException(ErrorCode.PROFILE_IN_USE, "보정은 최소 1개 이상 남아 있어야 합니다");
        }
        jdbc.update("DELETE FROM calib_profile WHERE id = ?", id);
    }

    public void deleteAll() {
        jdbc.update("DELETE FROM calib_profile");
    }

    public String nextDefaultName() {
        List<String> names = jdbc.query("SELECT name FROM calib_profile", (rs, i) -> rs.getString(1));
        for (int n = 1; ; n++) {
            String candidate = "내 보정 " + n;
            if (!names.contains(candidate)) {
                return candidate;
            }
        }
    }

    // ------------------------------------------------------------------ 내부

    private Map<String, Object> summaryRow(long id, String name, boolean active, String deviceLabel,
                                           Integer screenW, Integer screenH, Double avgErrorPx,
                                           Double maxErrorPx, String createdAt, String lastUsedAt) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("id", id);
        m.put("name", name);
        m.put("active", active);
        m.put("deviceLabel", deviceLabel);
        m.put("screenW", screenW);
        m.put("screenH", screenH);
        m.put("avgErrorPx", avgErrorPx);
        m.put("maxErrorPx", maxErrorPx);
        m.put("thresholdPx", THRESHOLD_PX);
        m.put("pass", avgErrorPx != null && avgErrorPx <= THRESHOLD_PX);
        m.put("createdAt", createdAt);
        m.put("lastUsedAt", lastUsedAt);
        return m;
    }

    private Map<String, Object> require(long id) {
        List<Map<String, Object>> rows = jdbc.query(
                "SELECT id, name, active, npz_sha256, screen_w, screen_h FROM calib_profile WHERE id = ?",
                (rs, i) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", rs.getLong("id"));
                    m.put("name", rs.getString("name"));
                    m.put("active", rs.getInt("active") == 1);
                    m.put("npzSha256", rs.getString("npz_sha256"));
                    m.put("screenW", rs.getObject("screen_w") == null ? null : rs.getInt("screen_w"));
                    m.put("screenH", rs.getObject("screen_h") == null ? null : rs.getInt("screen_h"));
                    return m;
                }, id);
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.PROFILE_NOT_FOUND, "해당 보정이 없습니다: " + id);
        }
        return rows.get(0);
    }

    private void notifyCalibChanged(long id, String sha256, Integer screenW, Integer screenH) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("id", id);
        body.put("sha256", sha256);
        body.put("screenW", screenW);
        body.put("screenH", screenH);
        agentHub.send("calib_changed", body);
    }
}
