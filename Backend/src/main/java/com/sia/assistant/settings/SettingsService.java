package com.sia.assistant.settings;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.Times;
import com.sia.assistant.relay.AgentSyncNotifier;
import com.sia.assistant.ws.FeHub;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.NullNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * app_settings 싱글턴(id=1)의 관리자.
 * settings_json 은 자유 JSON 이고 미지의 키는 그대로 보관·반환한다.
 * 다만 <b>알려진 키</b>(SettingsSchema — BE·AI 가 읽어서 동작이 달라지는 값)는 예외다:
 * 읽기는 peekSessionSeconds·peekString 이, 저장 시 완전성·타입 검사는 replace 가 한다.
 */
@Service
public class SettingsService {

    private static final Logger log = LoggerFactory.getLogger(SettingsService.class);
    private static final String SEED_PATH = "seed/default-settings.json";
    /**
     * 시드 파일까지 못 읽는 최악의 경우를 위한 마지막 보루 (default-settings.json 과 동일 값).
     * V1 시드에는 micDeviceId·cameraDeviceId 가 없다 — 나중에 추가된 키라 기존 DB 는 첫 저장 때
     * fillMissing 이 이 시드에서 채운다 (마이그레이션 없이 끝난다 · SettingsSchema 참고).
     */
    private static final String FALLBACK_SEED =
            "{\"wakeWord\":\"시아야\",\"sessionSeconds\":15,"
                    + "\"autoStart\":true,\"gazeCursor\":false,\"micDevice\":null,\"cameraDevice\":null,"
                    + "\"micDeviceId\":null,\"cameraDeviceId\":null}";

    private final JdbcTemplate jdbc;
    private final ObjectMapper om;
    private final FeHub feHub;
    // 통지 페이로드 조립은 AgentSyncNotifier 한 곳이다 — 순환은 지연 조회로 끊는다
    private final ObjectProvider<AgentSyncNotifier> notifierProvider;

    private record Row(String json, int version, String updatedAt,
                       Integer agentSyncedVersion, String agentSyncedAt, String agentVersion) {
    }

    public SettingsService(JdbcTemplate jdbc, ObjectMapper om, FeHub feHub,
                           ObjectProvider<AgentSyncNotifier> notifierProvider) {
        this.jdbc = jdbc;
        this.om = om;
        this.feHub = feHub;
        this.notifierProvider = notifierProvider;
    }

    /** {version, updatedAt, agentSyncedVersion, agentSyncedAt, agentVersion, settingsPending, settings} */
    public Map<String, Object> get() {
        Row r = row();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("version", r.version());
        body.put("updatedAt", r.updatedAt());
        body.put("agentSyncedVersion", r.agentSyncedVersion());
        body.put("agentSyncedAt", r.agentSyncedAt());
        body.put("agentVersion", r.agentVersion());
        body.put("settingsPending", r.agentSyncedVersion() == null || r.agentSyncedVersion() < r.version());
        body.put("settings", parse(r.json()));
        return body;
    }

    /**
     * 설정 전체 교체. 문서가 들고 온 updatedAt 이 저장분보다 과거면 낙관적 잠금 실패(SETTINGS_STALE).
     * version+1 과 updatedAt 은 서버가 다시 찍는다. 저장 후 에이전트에 settings_changed 통지.
     *
     * @return 새 settings_version
     */
    public synchronized int replace(JsonNode settings, String clientUpdatedAt) {
        if (settings == null || !settings.isObject()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "설정 본문은 JSON 객체여야 합니다");
        }
        Row r = row();
        // 고정폭 UTC 문자열이라 문자열 비교 = 시간 비교
        if (clientUpdatedAt != null && !clientUpdatedAt.isBlank()
                && r.updatedAt() != null && clientUpdatedAt.compareTo(r.updatedAt()) < 0) {
            throw new ApiException(ErrorCode.SETTINGS_STALE,
                    "다른 곳에서 먼저 저장된 설정이 있습니다. 최신 설정을 불러온 뒤 다시 저장해 주세요");
        }
        // ★ 통째 교체이지만 알려진 키는 유실되지 않는다 (SettingsSchema 참고) —
        //   micDevice 하나가 빠지면 이후 프로필의 장비 라벨이 비어 자동 맵핑이 영구히 깨진다.
        ObjectNode merged = ((ObjectNode) settings).deepCopy();
        List<String> filled = SettingsSchema.fillMissing(merged, parse(r.json()), parse(readSeed()));
        SettingsSchema.validate(merged);   // 타입이 틀리면 저장 없이 INVALID_REQUEST
        if (!filled.isEmpty()) {
            log.warn("설정 저장 본문에 알려진 키 {} 가 없어 기존 값으로 채웠습니다 — 클라이언트는 GET 으로 읽은"
                    + " settings 를 그대로 돌려보내야 합니다", filled);
        }
        int newVersion = r.version() + 1;
        jdbc.update("UPDATE app_settings SET settings_json = ?, settings_version = ?, settings_updated_at = ? WHERE id = 1",
                merged.toString(), newVersion, Times.now());
        notifySettingsChanged();
        return newVersion;
    }

    public int version() {
        Integer v = jdbc.queryForObject("SELECT settings_version FROM app_settings WHERE id = 1", Integer.class);
        return v == null ? 1 : v;
    }

    public String rawJson() {
        return jdbc.queryForObject("SELECT settings_json FROM app_settings WHERE id = 1", String.class);
    }

    /**
     * settings_json 에서 sessionSeconds 만 읽는다. 없거나 0 이하·파싱 실패면 기본값(15).
     * SessionService 가 세션을 열거나 갱신할 때마다 부르므로, 설정을 바꾸면
     * <b>다음 개시·갱신부터</b> 새 값이 적용된다 (진행 중인 세션의 마감시각은 그대로).
     */
    public int peekSessionSeconds() {
        try {
            int v = om.readTree(rawJson()).path("sessionSeconds").asInt(0);
            return v > 0 ? v : SettingsSchema.DEFAULT_SESSION_SECONDS;
        } catch (Exception e) {
            log.warn("sessionSeconds 읽기 실패 — 기본값 {}초를 씁니다",
                    SettingsSchema.DEFAULT_SESSION_SECONDS, e);
            return SettingsSchema.DEFAULT_SESSION_SECONDS;
        }
    }

    /** settings_json 의 문자열 키 하나(wakeWord·micDevice·cameraDevice 등)를 읽는다. 없거나 실패하면 null. */
    public String peekString(String key) {
        try {
            JsonNode v = om.readTree(rawJson()).path(key);
            return v.isTextual() && !v.asText().isBlank() ? v.asText() : null;
        } catch (Exception e) {
            log.warn("설정 키 {} 읽기 실패 — null 로 둡니다", key, e);
            return null;
        }
    }

    /** 에이전트가 설정을 반영했음을 기록하고 FE 에 동기화 상태를 알린다. */
    public void ack(int version, String agentVersion) {
        jdbc.update("UPDATE app_settings SET agent_synced_version = ?, agent_synced_at = ?,"
                        + " agent_version = COALESCE(?, agent_version) WHERE id = 1",
                version, Times.now(), agentVersion);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("settingsVersion", version());
        body.put("agentSyncedVersion", version);
        feHub.send("settings_sync", body);
    }

    /** 설정을 시드(resources/seed/default-settings.json)로 되돌린다. version 은 계속 올라간다. */
    public synchronized void resetToSeed() {
        String seed = readSeed();
        int newVersion = version() + 1;
        jdbc.update("UPDATE app_settings SET settings_json = ?, settings_version = ?, settings_updated_at = ? WHERE id = 1",
                seed, newVersion, Times.now());
    }

    /**
     * 설정 저장·blob 변경 때 에이전트에 보내는 통지 — 페이로드 조립은 AgentSyncNotifier.
     * 프로필 활성 교체·제스처 토글은 각 서비스가 AgentSyncNotifier 를 직접 부른다 (PROTOCOL.md §4.2).
     */
    void notifySettingsChanged() {
        AgentSyncNotifier notifier = notifierProvider.getIfAvailable();
        if (notifier != null) {
            notifier.notifySettingsChanged();
        }
    }

    private Row row() {
        return jdbc.queryForObject(
                "SELECT settings_json, settings_version, settings_updated_at,"
                        + " agent_synced_version, agent_synced_at, agent_version FROM app_settings WHERE id = 1",
                (rs, i) -> new Row(
                        rs.getString("settings_json"),
                        rs.getInt("settings_version"),
                        rs.getString("settings_updated_at"),
                        rs.getObject("agent_synced_version") == null ? null : rs.getInt("agent_synced_version"),
                        rs.getString("agent_synced_at"),
                        rs.getString("agent_version")));
    }

    private JsonNode parse(String json) {
        try {
            return om.readTree(json);
        } catch (Exception e) {
            log.error("settings_json 파싱 실패 — null 로 반환합니다", e);
            return NullNode.getInstance();
        }
    }

    private String readSeed() {
        try (InputStream in = new ClassPathResource(SEED_PATH).getInputStream()) {
            return new String(in.readAllBytes(), StandardCharsets.UTF_8).trim();
        } catch (Exception e) {
            log.error("설정 시드({}) 읽기 실패 — 내장 기본값을 씁니다", SEED_PATH, e);
            return FALLBACK_SEED;
        }
    }
}
