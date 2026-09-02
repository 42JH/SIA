package com.sia.assistant.profile;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.Times;
import com.sia.assistant.ws.AgentHub;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

/**
 * 보이스 프로필 규칙 — 최대 4개(사용 1 + 스톡 3), 첫 프로필 자동 활성,
 * 사용 중·마지막 1개 삭제 금지, 장비 맵핑 후보는 최근 사용일 내림차순 (회의 확정 2026-09-01).
 */
class VoiceProfileServiceTest {

    private SingleConnectionDataSource ds;
    private JdbcTemplate jdbc;
    private AgentHub agentHub;
    private VoiceProfileService service;

    @BeforeEach
    void setUp(@TempDir Path dir) {
        // 단일 커넥션 — saveNew 가 INSERT 직후 last_insert_rowid() 를 같은 커넥션에서 읽어야 한다
        // (운영은 @Transactional 이 커넥션을 고정한다).
        ds = new SingleConnectionDataSource("jdbc:sqlite:" + dir.resolve("voices-test.db"), true);
        Flyway.configure().dataSource(ds).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(ds);
        agentHub = mock(AgentHub.class);
        service = new VoiceProfileService(jdbc, agentHub);
    }

    @AfterEach
    void tearDown() {
        ds.destroy();
    }

    private long save(String name, String device) {
        return service.saveNew(name, new byte[]{1, 2, 3}, "sha-" + name, new byte[]{9}, "audio/webm",
                4.0, "양호", "낮음", device);
    }

    @Test
    @DisplayName("첫 프로필은 자동으로 사용 중이 되고 AI 에 voice_changed 가 나간다")
    void firstProfileAutoActivates() {
        long id = save(null, "Realtek Audio");

        assertThat(service.activeIdOrNull()).isEqualTo(id);
        assertThat(service.list().get(0))
                .containsEntry("name", "내 목소리 1")
                .containsEntry("active", true)
                .containsEntry("deviceLabel", "Realtek Audio");
        verify(agentHub).send(eq("voice_changed"), any());
    }

    @Test
    @DisplayName("최대 4개 — 5번째 등록은 PROFILE_LIMIT 으로 거절된다")
    void limitIsFourProfiles() {
        for (int i = 0; i < 4; i++) {
            save(null, "mic");
        }
        assertThatThrownBy(() -> save(null, "mic"))
                .isInstanceOfSatisfying(ApiException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.PROFILE_LIMIT));
    }

    @Test
    @DisplayName("기본 이름은 빈 번호를 찾는다 — '내 목소리 2' 를 지워도 재사용 충돌이 없다")
    void defaultNameSkipsTakenNumbers() {
        save(null, "mic");             // 내 목소리 1 (활성)
        long second = save(null, "mic"); // 내 목소리 2
        service.delete(second);
        save(null, "mic");             // 다시 내 목소리 2
        assertThat(service.list()).extracting(m -> m.get("name"))
                .containsExactlyInAnyOrder("내 목소리 1", "내 목소리 2");
    }

    @Test
    @DisplayName("사용으로 설정은 이전·새 활성 모두 최근 사용일을 찍는다")
    void activateStampsLastUsedOnBothSides() {
        long first = save(null, "mic");
        long second = save(null, "mic");

        service.activate(second);

        assertThat(service.activeIdOrNull()).isEqualTo(second);
        List<Map<String, Object>> items = service.list();
        assertThat(items).allSatisfy(m -> assertThat(m.get("lastUsedAt")).isNotNull());
        assertThat(items.get(0)).containsEntry("id", second); // 사용 중이 목록 맨 앞
    }

    @Test
    @DisplayName("사용 중이거나 마지막 1개인 보이스는 삭제할 수 없다 (와이어프레임 규칙)")
    void deleteRules() {
        long first = save(null, "mic");
        assertThatThrownBy(() -> service.delete(first))
                .isInstanceOfSatisfying(ApiException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.PROFILE_IN_USE));

        long second = save(null, "mic");
        service.delete(second); // 스톡은 지워진다
        assertThat(service.count()).isEqualTo(1);
    }

    @Test
    @DisplayName("장비 맵핑 후보는 최근 사용일 내림차순 — 2개 이상이면 사용자 질문의 재료가 된다")
    void byDeviceOrdersByLastUsed() {
        long a = save("A", "USB Mic");
        long b = save("B", "USB Mic");
        save("C", "다른 마이크");
        service.activate(b); // b 의 last_used_at 이 가장 최근

        List<Map<String, Object>> matches = service.byDevice("USB Mic");
        assertThat(matches).hasSize(2);
        assertThat(matches.get(0)).containsEntry("id", b);
        assertThat(matches.get(1)).containsEntry("id", a);
    }

    @Test
    @DisplayName("프로필별 정확도는 usage_event(kind=voice, profile_id)에서 집계된다 — 롤백 판단 근거")
    void accuracyAggregatesPerProfile() {
        long id = save(null, "mic");
        long other = save(null, "mic");
        insertVoiceEvent("e1", id, 0.9);
        insertVoiceEvent("e2", id, 0.7);
        insertVoiceEvent("e3", other, 0.1);

        Map<String, Object> accuracy = service.accuracyOf(id);
        assertThat((Double) accuracy.get("all")).isEqualTo(0.8);
        assertThat((Double) accuracy.get("d7")).isEqualTo(0.8);
    }

    @Test
    @DisplayName("화자 인식 후 샘플 갱신은 활성 프로필만 바꾼다")
    void updateActiveSampleTouchesActiveOnly() {
        long active = save(null, "mic");
        save(null, "mic");

        service.updateActiveSample(new byte[]{7, 7}, "audio/wav");

        VoiceProfileService.Sample sample = service.sample(active);
        assertThat(sample.mime()).isEqualTo("audio/wav");
        assertThat(sample.bytes()).containsExactly(7, 7);
    }

    private void insertVoiceEvent(String uid, long profileId, double accuracy) {
        jdbc.update("INSERT INTO usage_event (event_uid, profile_id, received_at, kind, accuracy, payload)"
                        + " VALUES (?, ?, ?, 'voice', ?, '{}')",
                uid, profileId, Times.now(), accuracy);
    }
}
