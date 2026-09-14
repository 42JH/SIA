package com.sia.assistant.settings;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.Sha256;
import com.sia.assistant.common.Times;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

/**
 * 전역 단일 npz(blob 테이블) 저장소. 이름은 wakeword 1종 — 호출어 모델.
 * (calib·speaker 는 프로필 다중화로 calib_profile·voice_profile 로, 커스텀 제스처 템플릿은
 *  2026-09-02 흐름도 03 정합으로 gesture.npz(제스처별)로 이동했다.)
 * sha256 이 에이전트 캐시 무효화 기준이자 GET 의 ETag 다.
 */
@Service
public class BlobService {

    public record Meta(String name, long byteSize, String sha256, String updatedAt) {
    }

    private static final Logger log = LoggerFactory.getLogger(BlobService.class);
    private static final List<String> NAMES = List.of("wakeword");
    private static final Set<String> NAME_SET = Set.copyOf(NAMES);
    private static final int MIN_BYTES = 1;
    private static final int MAX_BYTES = 5 * 1024 * 1024;

    private final JdbcTemplate jdbc;
    private final SettingsService settingsService;

    public BlobService(JdbcTemplate jdbc, SettingsService settingsService) {
        this.jdbc = jdbc;
        this.settingsService = settingsService;
    }

    /** 이름 전부의 sha256 — 없는 blob 은 null 값으로 들어간다 (blobs 페이로드 계약, PROTOCOL.md §0.1). */
    public Map<String, String> hashes() {
        Map<String, String> out = new LinkedHashMap<>();
        for (String name : NAMES) {
            out.put(name, null);
        }
        jdbc.query("SELECT name, sha256 FROM blob", rs -> {
            out.put(rs.getString("name"), rs.getString("sha256"));
        });
        return out;
    }

    public byte[] payload(String name) {
        requireKnown(name);
        List<byte[]> rows = jdbc.query("SELECT payload FROM blob WHERE name = ?",
                (rs, i) -> rs.getBytes("payload"), name);
        if (rows.isEmpty()) {
            throw new ApiException(ErrorCode.BLOB_NOT_FOUND, "저장된 데이터가 없습니다: " + name);
        }
        return rows.get(0);
    }

    public Optional<Meta> meta(String name) {
        requireKnown(name);
        List<Meta> rows = jdbc.query(
                "SELECT name, byte_size, sha256, updated_at FROM blob WHERE name = ?",
                (rs, i) -> new Meta(
                        rs.getString("name"),
                        rs.getLong("byte_size"),
                        rs.getString("sha256"),
                        rs.getString("updated_at")),
                name);
        return rows.stream().findFirst();
    }

    /**
     * 업로드(UPSERT). 저장된 것과 sha256 이 같으면 저장을 생략하고 false 를 반환한다.
     * 실제로 저장되면 에이전트에 settings_changed(blob 해시 갱신)를 통지하고 true.
     */
    public boolean put(String name, byte[] payload) {
        requireKnown(name);
        if (payload == null || payload.length < MIN_BYTES || payload.length > MAX_BYTES) {
            throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "업로드 크기는 1바이트 이상 5MB 이하여야 합니다");
        }
        String sha256 = Sha256.hex(payload);
        String existing = jdbc.query("SELECT sha256 FROM blob WHERE name = ?",
                (rs, i) -> rs.getString(1), name).stream().findFirst().orElse(null);
        if (sha256.equalsIgnoreCase(existing)) {
            return false; // 내용이 같다 — 저장·통지 모두 생략
        }
        jdbc.update("INSERT INTO blob (name, payload, byte_size, sha256, updated_at)"
                        + " VALUES (?, ?, ?, ?, ?)"
                        + " ON CONFLICT(name) DO UPDATE SET payload = excluded.payload,"
                        + " byte_size = excluded.byte_size, sha256 = excluded.sha256,"
                        + " updated_at = excluded.updated_at",
                name, payload, payload.length, sha256, Times.now());
        log.info("blob '{}' 저장 — {} bytes, sha256={}", name, payload.length, sha256);
        settingsService.notifySettingsChanged();
        return true;
    }

    public void deleteAll() {
        jdbc.update("DELETE FROM blob");
    }

    private static void requireKnown(String name) {
        if (name == null || !NAME_SET.contains(name)) {
            throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "알 수 없는 데이터 이름입니다. wakeword 만 사용할 수 있습니다"
                            + " (커스텀 제스처 템플릿은 /api/agent/gestures/{id}/npz, 시선 보정·보이스는 프로필 API 를 사용하세요)");
        }
    }
}
