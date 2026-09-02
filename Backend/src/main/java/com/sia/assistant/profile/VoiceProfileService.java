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
 * 보이스(화자) 프로필 저장소 — 최대 4개 (사용 1 + 스톡 3), 와이어프레임 보이스 섹션의 원천.
 * 등록 진행 중 임시본은 VoiceRegistrationOrchestrator 메모리에 있고, 여기는 확정본만 다룬다.
 * 프로필마다 등록 당시 마이크 이름(device_label)과 최근 사용일(last_used_at)을 갖는다 —
 * 장비 교체 시 자동 맵핑과 "어느 데이터를 쓸까" 질문(DeviceRemapController)의 근거다.
 */
@Service
public class VoiceProfileService {

    public static final int MAX_PROFILES = 4;

    public record Sample(byte[] bytes, String mime) {
    }

    private final JdbcTemplate jdbc;
    private final AgentHub agentHub;

    public VoiceProfileService(JdbcTemplate jdbc, AgentHub agentHub) {
        this.jdbc = jdbc;
        this.agentHub = agentHub;
    }

    // ------------------------------------------------------------------ 조회

    /** AI blobs 페이로드의 voice 항목 — {id, sha256} 또는 null (PROTOCOL.md §0.1). */
    public Map<String, Object> activeRefOrNull() {
        List<Map<String, Object>> rows = jdbc.query(
                "SELECT id, npz_sha256 FROM voice_profile WHERE active = 1 LIMIT 1",
                (rs, i) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", rs.getLong("id"));
                    m.put("sha256", rs.getString("npz_sha256"));
                    return m;
                });
        return rows.isEmpty() ? null : rows.get(0);
    }

    public Long activeIdOrNull() {
        List<Long> ids = jdbc.query("SELECT id FROM voice_profile WHERE active = 1 LIMIT 1",
                (rs, i) -> rs.getLong(1));
        return ids.isEmpty() ? null : ids.get(0);
    }

    public int count() {
        Integer n = jdbc.queryForObject("SELECT COUNT(*) FROM voice_profile", Integer.class);
        return n == null ? 0 : n;
    }

    /**
     * FE 목록 — 사용 중이 먼저, 그다음 등록일 순.
     * accuracy 는 usage_event(kind=voice, profile_id)에서 직접 집계한다 — 프로필별 정확도를
     * 따로 보관하는 이유는 재등록이 더 나쁠 때 이전 프로필로 롤백할 근거를 남기기 위해서다.
     */
    public List<Map<String, Object>> list() {
        List<Map<String, Object>> items = jdbc.query(
                "SELECT id, name, active, device_label, duration_sec, quality, noise,"
                        + " sample_bytes, created_at, last_used_at FROM voice_profile"
                        + " ORDER BY active DESC, created_at ASC, id ASC",
                (rs, i) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    long id = rs.getLong("id");
                    m.put("id", id);
                    m.put("name", rs.getString("name"));
                    m.put("active", rs.getInt("active") == 1);
                    m.put("deviceLabel", rs.getString("device_label"));
                    m.put("durationSec", rs.getObject("duration_sec") == null ? null : rs.getDouble("duration_sec"));
                    m.put("quality", rs.getString("quality"));
                    m.put("noise", rs.getString("noise"));
                    m.put("sampleUrl", rs.getObject("sample_bytes") == null ? null : "/api/voices/" + id + "/sample");
                    m.put("createdAt", rs.getString("created_at"));
                    m.put("lastUsedAt", rs.getString("last_used_at"));
                    return m;
                });
        for (Map<String, Object> item : items) {
            item.put("accuracy", accuracyOf((Long) item.get("id")));
        }
        return items;
    }

    /** 프로필별 음성 인식 정확도 — {d7, d30, all} (데이터 없으면 null 값). */
    public Map<String, Object> accuracyOf(long id) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("d7", avgAccuracySince(id, Times.daysAgo(7)));
        out.put("d30", avgAccuracySince(id, Times.daysAgo(30)));
        out.put("all", avgAccuracySince(id, null));
        return out;
    }

    public Sample sample(long id) {
        List<Sample> rows = jdbc.query(
                "SELECT sample, sample_mime FROM voice_profile WHERE id = ? AND sample IS NOT NULL",
                (rs, i) -> new Sample(rs.getBytes("sample"), rs.getString("sample_mime")), id);
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.PROFILE_NOT_FOUND, "저장된 샘플 오디오가 없습니다");
        }
        return rows.get(0);
    }

    public byte[] npz(long id) {
        List<byte[]> rows = jdbc.query(
                "SELECT npz FROM voice_profile WHERE id = ? AND npz IS NOT NULL",
                (rs, i) -> rs.getBytes("npz"), id);
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.PROFILE_NOT_FOUND, "저장된 보이스 데이터가 없습니다");
        }
        return rows.get(0);
    }

    /** 활성 프로필의 npz — AI 캐시 갱신용 (GET /api/agent/voices/active/npz). */
    public Map<String, Object> activeNpzMeta() {
        List<Map<String, Object>> rows = jdbc.query(
                "SELECT id, npz_sha256 FROM voice_profile WHERE active = 1 AND npz IS NOT NULL LIMIT 1",
                (rs, i) -> Map.<String, Object>of("id", rs.getLong("id"), "sha256", rs.getString("npz_sha256")));
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.PROFILE_NOT_FOUND, "사용 중인 보이스가 없습니다");
        }
        return rows.get(0);
    }

    /** 장비 이름으로 후보 조회 — 자동 맵핑(1개)·사용자 질문(2개 이상)의 재료. 최근 사용일 내림차순. */
    public List<Map<String, Object>> byDevice(String deviceLabel) {
        return jdbc.query(
                "SELECT id, name, active, created_at, last_used_at FROM voice_profile"
                        + " WHERE device_label = ?"
                        + " ORDER BY COALESCE(last_used_at, created_at) DESC, id DESC",
                (rs, i) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", rs.getLong("id"));
                    m.put("name", rs.getString("name"));
                    m.put("active", rs.getInt("active") == 1);
                    m.put("createdAt", rs.getString("created_at"));
                    m.put("lastUsedAt", rs.getString("last_used_at"));
                    return m;
                }, deviceLabel);
    }

    // ------------------------------------------------------------------ 변경

    /**
     * 등록 확정 — 오케스트레이터가 voice_commit 에서 부른다.
     * 첫 프로필이면 자동으로 사용 중이 된다 (온보딩). 이후 추가분은 스톡으로 남고
     * 활성화는 사용자의 "사용으로 설정"(activate)이다.
     *
     * @return 새 프로필 id
     */
    @Transactional
    public long saveNew(String nameOrNull, byte[] npz, String npzSha256, byte[] sample, String sampleMime,
                        Double durationSec, String quality, String noise, String deviceLabel) {
        if (count() >= MAX_PROFILES) {
            throw new ApiException(ErrorCode.PROFILE_LIMIT,
                    "보이스는 최대 " + MAX_PROFILES + "개까지 저장할 수 있습니다. 먼저 사용하지 않는 보이스를 삭제해 주세요");
        }
        String name = (nameOrNull == null || nameOrNull.isBlank()) ? nextDefaultName() : nameOrNull.trim();
        boolean first = count() == 0;
        String now = Times.now();
        jdbc.update("INSERT INTO voice_profile (name, active, device_label, npz, npz_sha256, npz_bytes,"
                        + " sample, sample_mime, sample_bytes, sample_updated_at,"
                        + " duration_sec, quality, noise, created_at, last_used_at)"
                        + " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                name, first ? 1 : 0, deviceLabel, npz, npzSha256, npz == null ? null : npz.length,
                sample, sampleMime, sample == null ? null : sample.length, sample == null ? null : now,
                durationSec, quality, noise, now, first ? now : null);
        Long id = jdbc.queryForObject("SELECT last_insert_rowid()", Long.class);
        if (first) {
            notifyVoiceChanged(id, npzSha256);
        }
        return id;
    }

    /** 사용으로 설정 — 이전 활성과 새 활성 모두 최근 사용일을 찍고, AI 에 voice_changed 를 보낸다. */
    @Transactional
    public Map<String, Object> activate(long id) {
        Map<String, Object> target = require(id);
        String now = Times.now();
        jdbc.update("UPDATE voice_profile SET active = 0, last_used_at = ? WHERE active = 1", now);
        jdbc.update("UPDATE voice_profile SET active = 1, last_used_at = ? WHERE id = ?", now, id);
        notifyVoiceChanged(id, (String) target.get("npzSha256"));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", id);
        out.put("name", target.get("name"));
        return out;
    }

    public void rename(long id, String name) {
        if (name == null || name.isBlank()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "보이스 이름이 필요합니다");
        }
        if (jdbc.update("UPDATE voice_profile SET name = ? WHERE id = ?", name.trim(), id) == 0) {
            throw new ApiException(ErrorCode.PROFILE_NOT_FOUND, "해당 보이스가 없습니다: " + id);
        }
    }

    /** 완전 삭제 — 사용 중이거나 마지막 1개면 거부 (와이어프레임 삭제 규칙 그대로). */
    @Transactional
    public void delete(long id) {
        Map<String, Object> target = require(id);
        if (Boolean.TRUE.equals(target.get("active"))) {
            throw new ApiException(ErrorCode.PROFILE_IN_USE,
                    "사용 중인 보이스는 삭제할 수 없습니다. 먼저 다른 보이스를 사용으로 설정해 주세요");
        }
        if (count() <= 1) {
            throw new ApiException(ErrorCode.PROFILE_IN_USE, "보이스는 최소 1개 이상 남아 있어야 합니다");
        }
        jdbc.update("DELETE FROM voice_profile WHERE id = ?", id);
    }

    /** 화자 인식 시 마지막 발화로 샘플 갱신 (PUT /api/agent/voices/active/sample). */
    public void updateActiveSample(byte[] bytes, String mime) {
        int updated = jdbc.update(
                "UPDATE voice_profile SET sample = ?, sample_mime = ?, sample_bytes = ?, sample_updated_at = ?"
                        + " WHERE active = 1",
                bytes, mime, bytes.length, Times.now());
        if (updated == 0) {
            throw new ApiException(ErrorCode.PROFILE_NOT_FOUND, "사용 중인 보이스가 없습니다");
        }
    }

    public void deleteAll() {
        jdbc.update("DELETE FROM voice_profile");
    }

    /** "내 목소리 N" — 재사용으로 인한 충돌을 피하려고 지금까지 만든 개수+1 이 아니라 빈 번호를 찾는다. */
    public String nextDefaultName() {
        List<String> names = jdbc.query("SELECT name FROM voice_profile", (rs, i) -> rs.getString(1));
        for (int n = 1; ; n++) {
            String candidate = "내 목소리 " + n;
            if (!names.contains(candidate)) {
                return candidate;
            }
        }
    }

    // ------------------------------------------------------------------ 내부

    private Map<String, Object> require(long id) {
        List<Map<String, Object>> rows = jdbc.query(
                "SELECT id, name, active, npz_sha256 FROM voice_profile WHERE id = ?",
                (rs, i) -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("id", rs.getLong("id"));
                    m.put("name", rs.getString("name"));
                    m.put("active", rs.getInt("active") == 1);
                    m.put("npzSha256", rs.getString("npz_sha256"));
                    return m;
                }, id);
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.PROFILE_NOT_FOUND, "해당 보이스가 없습니다: " + id);
        }
        return rows.get(0);
    }

    private void notifyVoiceChanged(long id, String sha256) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("id", id);
        body.put("sha256", sha256);
        agentHub.send("voice_changed", body);
    }

    private Double avgAccuracySince(long id, String sinceOrNull) {
        String base = "SELECT AVG(accuracy) FROM usage_event"
                + " WHERE kind = 'voice' AND profile_id = ? AND accuracy IS NOT NULL";
        if (sinceOrNull == null) {
            return jdbc.queryForObject(base, Double.class, id);
        }
        return jdbc.queryForObject(base + " AND received_at >= ?", Double.class, id, sinceOrNull);
    }
}
