package com.sia.assistant.settings;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.any;
import static org.mockito.Mockito.anyString;
import static org.mockito.Mockito.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.startsWith;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.relay.AgentSyncNotifier;
import com.sia.assistant.ws.FeHub;
import java.sql.ResultSet;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;

class SettingsServiceTest {

    private static final String RAW_JSON_SQL = "SELECT settings_json FROM app_settings WHERE id = 1";
    private static final String VERSION_SQL = "SELECT settings_version FROM app_settings WHERE id = 1";

    private JdbcTemplate jdbc;
    private AgentSyncNotifier notifier;
    private FeHub feHub;
    private SettingsService service;
    private final ObjectMapper om = new ObjectMapper();

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        jdbc = mock(JdbcTemplate.class);
        notifier = mock(AgentSyncNotifier.class);
        feHub = mock(FeHub.class);
        ObjectProvider<AgentSyncNotifier> notifierProvider = mock(ObjectProvider.class);
        when(notifierProvider.getIfAvailable()).thenReturn(notifier);
        service = new SettingsService(jdbc, om, feHub, notifierProvider);
    }

    /** row() 조회를 흉내 낸다 — 매퍼에 가짜 ResultSet 을 먹여 실제 매핑 코드까지 태운다. */
    @SuppressWarnings({"unchecked", "rawtypes"})
    private void stubRow(String json, int version, String updatedAt, Integer syncedVersion) {
        when(jdbc.queryForObject(startsWith("SELECT settings_json,"), any(RowMapper.class)))
                .thenAnswer(inv -> {
                    ResultSet rs = mock(ResultSet.class);
                    when(rs.getString("settings_json")).thenReturn(json);
                    when(rs.getInt("settings_version")).thenReturn(version);
                    when(rs.getString("settings_updated_at")).thenReturn(updatedAt);
                    when(rs.getObject("agent_synced_version")).thenReturn(syncedVersion);
                    if (syncedVersion != null) {
                        when(rs.getInt("agent_synced_version")).thenReturn(syncedVersion);
                    }
                    RowMapper mapper = inv.getArgument(1);
                    return mapper.mapRow(rs, 1);
                });
    }

    @Test
    @DisplayName("에이전트가 아직 동기화하지 않았으면 settingsPending 이다")
    void unsyncedSettingsArePending() {
        stubRow("{\"wakeWord\":\"시아\"}", 3, "2026-08-28 10:00:00.000", null);

        Map<String, Object> body = service.get();

        assertThat(body)
                .containsEntry("version", 3)
                .containsEntry("settingsPending", true);
        // ★ settings 는 JsonNode 가 아니라 Map 이다 — 응답 직렬화가 Jackson 3 컨버터를 타기 때문이다
        //   (SettingsService.asMap · SettingsControllerJsonTest 참고)
        assertThat(body.get("settings")).isEqualTo(Map.of("wakeWord", "시아"));
    }

    @Test
    @DisplayName("동기화 버전이 따라잡았으면 settingsPending 이 아니다")
    void syncedSettingsAreNotPending() {
        stubRow("{}", 3, "2026-08-28 10:00:00.000", 3);

        assertThat(service.get()).containsEntry("settingsPending", false);
    }

    @Test
    @DisplayName("설정 본문이 JSON 객체가 아니면 INVALID_REQUEST 다")
    void replaceRejectsNonObject() throws Exception {
        assertThatThrownBy(() -> service.replace(null, null))
                .isInstanceOfSatisfying(ApiException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.INVALID_REQUEST));
        assertThatThrownBy(() -> service.replace(om.readTree("[1,2]"), null))
                .isInstanceOf(ApiException.class);
    }

    @Test
    @DisplayName("저장분보다 과거의 updatedAt 을 들고 오면 낙관적 잠금 실패(SETTINGS_STALE)다")
    void replaceRejectsStaleClient() throws Exception {
        stubRow("{}", 3, "2026-08-28 10:00:00.000", null);

        assertThatThrownBy(() -> service.replace(om.readTree("{\"a\":1}"), "2026-08-28 09:59:59.999"))
                .isInstanceOfSatisfying(ApiException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.SETTINGS_STALE));
    }

    @Test
    @DisplayName("replace 는 version+1 로 저장하고 에이전트 동기화 통지(AgentSyncNotifier)를 부른다")
    void replaceBumpsVersionAndNotifiesAgent() throws Exception {
        stubRow("{}", 3, "2026-08-28 10:00:00.000", null);

        int newVersion = service.replace(om.readTree("{\"a\":1}"), "2026-08-28 10:00:00.000");

        assertThat(newVersion).isEqualTo(4);
        // 미지의 키(a)는 그대로 저장되고, 알려진 키는 시드 값으로 채워진다 (SettingsSchema)
        verify(jdbc).update(startsWith("UPDATE app_settings SET settings_json"),
                storedJson(s -> s.contains("\"a\":1") && s.contains("\"wakeWord\":\"시아\"")),
                eq(4), anyString());
        verify(notifier).notifySettingsChanged();
    }

    @Test
    @DisplayName("부분 문서를 저장해도 알려진 키는 기존 값으로 살아남는다 — micDevice 유실이 프로필 맵핑을 깨뜨리지 않도록")
    void partialPutKeepsKnownKeys() throws Exception {
        stubRow("{\"wakeWord\":\"시아\",\"sessionSeconds\":15,\"autoStart\":true,\"gazeCursor\":true,"
                + "\"micDevice\":\"마이크(Realtek(R) Audio)\",\"cameraDevice\":\"HD Webcam\"}",
                3, "2026-08-28 10:00:00.000", 3);

        service.replace(om.readTree("{\"wakeWord\":\"시아\",\"sessionSeconds\":60}"), null);

        verify(jdbc).update(startsWith("UPDATE app_settings SET settings_json"),
                storedJson(s -> s.contains("\"micDevice\":\"마이크(Realtek(R) Audio)\"")
                        && s.contains("\"cameraDevice\":\"HD Webcam\"")
                        && s.contains("\"gazeCursor\":true")
                        && s.contains("\"sessionSeconds\":60")),   // 보낸 값은 그대로 저장된다
                eq(4), anyString());
    }

    @Test
    @DisplayName("알려진 키의 타입이 틀리면 저장하지 않고 INVALID_REQUEST 다")
    void wrongTypeIsRejectedBeforeSaving() throws Exception {
        stubRow("{}", 3, "2026-08-28 10:00:00.000", null);

        assertThatThrownBy(() -> service.replace(om.readTree("{\"sessionSeconds\":0}"), null))
                .isInstanceOfSatisfying(ApiException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.INVALID_REQUEST));
        verify(jdbc, never()).update(startsWith("UPDATE app_settings SET settings_json"),
                any(), any(), any());
    }

    /** jdbc.update 의 가변 인자 자리에서 저장될 JSON 문자열만 검사한다. */
    private static Object storedJson(java.util.function.Predicate<String> check) {
        return org.mockito.ArgumentMatchers.argThat(v -> v instanceof String s && check.test(s));
    }

    @Test
    @DisplayName("peekString 은 문자열 키를 읽고, 없거나 공백·파싱 불가면 null 이다")
    void peekStringReadsOptionalKeys() {
        when(jdbc.queryForObject(RAW_JSON_SQL, String.class))
                .thenReturn("{\"micDevice\":\"Realtek Audio\",\"cameraDevice\":\"\"}");
        assertThat(service.peekString("micDevice")).isEqualTo("Realtek Audio");
        assertThat(service.peekString("cameraDevice")).isNull();
        assertThat(service.peekString("wakeWord")).isNull();

        when(jdbc.queryForObject(RAW_JSON_SQL, String.class)).thenThrow(new RuntimeException("db down"));
        assertThat(service.peekString("micDevice")).isNull();
    }

    @Test
    @DisplayName("클라이언트가 updatedAt 을 안 들고 오면 잠금 검사 없이 저장된다")
    void replaceWithoutClientTimestampPasses() throws Exception {
        stubRow("{}", 3, "2026-08-28 10:00:00.000", null);

        assertThat(service.replace(om.readTree("{}"), null)).isEqualTo(4);
    }

    @Test
    @DisplayName("peekSessionSeconds 는 설정값을 읽고, 없거나 0 이하·파싱 불가면 15 이다")
    void peekSessionSecondsFallsBackTo15() {
        when(jdbc.queryForObject(RAW_JSON_SQL, String.class)).thenReturn("{\"sessionSeconds\":45}");
        assertThat(service.peekSessionSeconds()).isEqualTo(45);

        when(jdbc.queryForObject(RAW_JSON_SQL, String.class)).thenReturn("{}");
        assertThat(service.peekSessionSeconds()).isEqualTo(15);

        when(jdbc.queryForObject(RAW_JSON_SQL, String.class)).thenReturn("{\"sessionSeconds\":0}");
        assertThat(service.peekSessionSeconds()).isEqualTo(15);

        when(jdbc.queryForObject(RAW_JSON_SQL, String.class)).thenThrow(new RuntimeException("db down"));
        assertThat(service.peekSessionSeconds()).isEqualTo(15);
    }

    @Test
    @DisplayName("ack 는 동기화 버전을 기록하고 FE 에 settings_sync 를 보낸다")
    void ackRecordsSyncAndNotifiesFe() {
        when(jdbc.queryForObject(VERSION_SQL, Integer.class)).thenReturn(5);

        service.ack(5, "0.9.0");

        verify(jdbc).update(startsWith("UPDATE app_settings SET agent_synced_version"),
                eq(5), anyString(), eq("0.9.0"));
        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> captor = ArgumentCaptor.forClass(Map.class);
        verify(feHub).send(eq("settings_sync"), captor.capture());
        assertThat(captor.getValue())
                .containsEntry("settingsVersion", 5)
                .containsEntry("agentSyncedVersion", 5);
    }

    @Test
    @DisplayName("resetToSeed 는 버전을 계속 올리며 시드로 되돌린다")
    void resetToSeedKeepsVersionMonotonic() {
        when(jdbc.queryForObject(VERSION_SQL, Integer.class)).thenReturn(3);

        service.resetToSeed();

        verify(jdbc).update(startsWith("UPDATE app_settings SET settings_json"),
                anyString(), eq(4), anyString());
    }
}
