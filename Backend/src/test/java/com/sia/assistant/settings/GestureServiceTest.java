package com.sia.assistant.settings;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.Sha256;
import com.sia.assistant.common.Times;
import com.sia.assistant.config.DataDirs;
import com.sia.assistant.relay.AgentSyncNotifier;
import com.sia.assistant.ws.AgentHub;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;
import tools.jackson.databind.ObjectMapper;

/**
 * 커스텀 제스처 템플릿은 제스처별 npz 다 (흐름도 03, 2026-09-02) — 행마다 npz·sha256, blobs.gestures 참조 목록,
 * 기본 제공 제스처(custom=0)는 템플릿이 없고 그 이름을 가로챌 수 없다. 이름 변경·삭제 통지는 id 를 싣는다.
 */
class GestureServiceTest {

    private static final byte[] NPZ_A = {1, 2, 3};
    private static final byte[] NPZ_B = {4, 5, 6, 7};

    private SingleConnectionDataSource ds;
    private JdbcTemplate jdbc;
    private AgentHub agentHub;
    private AgentSyncNotifier notifier;
    private GestureService service;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp(@TempDir Path dir) {
        // 단일 커넥션 — saveCustom 이 INSERT 직후 last_insert_rowid() 를 같은 커넥션에서 읽어야 한다
        ds = new SingleConnectionDataSource("jdbc:sqlite:" + dir.resolve("gestures-test.db"), true);
        Flyway.configure().dataSource(ds).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(ds);
        // 스텝 검증이 tool 행을 보므로 하나 심는다 (운영은 ToolCatalogSync 가 채운다)
        jdbc.update("INSERT INTO tool (name, description, input_schema_json, session_required, confirm_required,"
                + " available, synced_at) VALUES ('scroll.step', 'd', '{}', 1, 0, 1, ?)", Times.now());
        // 기본 제공 제스처 한 종 — DefaultGestures 와 같은 형태 (custom=0, npz 없음, 한손 정적, 스텝 없음)
        jdbc.update("INSERT INTO gesture (custom, kind, context, name, label, repeatable, hands, motion)"
                + " VALUES (0, 'HAND', NULL, 'Open_Palm', '손바닥 펴기', 0, 1, 'STATIC')");
        agentHub = mock(AgentHub.class);
        notifier = mock(AgentSyncNotifier.class);
        ObjectProvider<AgentSyncNotifier> notifierProvider = mock(ObjectProvider.class);
        when(notifierProvider.getIfAvailable()).thenReturn(notifier);
        service = new GestureService(jdbc, new ObjectMapper(), agentHub, new DataDirs(dir.toString()),
                notifierProvider);
    }

    @AfterEach
    void tearDown() {
        ds.destroy();
    }

    private long save(String name, byte[] npz) {
        return save(name, npz, 2, "DYNAMIC");
    }

    private long save(String name, byte[] npz, Integer hands, String motion) {
        return service.saveCustom(name, "라벨", null, null, false,
                List.of(new GestureService.Step("scroll.step", Map.of("dir", "up"), null)), npz, Sha256.hex(npz),
                hands, motion);
    }

    @Test
    @DisplayName("커스텀 제스처마다 npz 가 따로 저장되고 blobs.gestures 에 {id, name, sha256} 로 나열된다 — blob 테이블은 쓰지 않는다")
    void perGestureNpz() {
        long a = save("손가락 하트", NPZ_A);
        long b = save("브이", NPZ_B);

        assertThat(service.npz(a)).isEqualTo(NPZ_A);
        assertThat(service.npz(b)).isEqualTo(NPZ_B);
        assertThat(service.npzMeta(b).sha256()).isEqualTo(Sha256.hex(NPZ_B));
        assertThat(service.npzMeta(b).bytes()).isEqualTo(4L);

        List<Map<String, Object>> refs = service.customNpzRefs();
        assertThat(refs).extracting(r -> r.get("id")).containsExactly(a, b);
        assertThat(refs).extracting(r -> r.get("sha256")).containsExactly(Sha256.hex(NPZ_A), Sha256.hex(NPZ_B));
        assertThat(service.getOne(a)).containsEntry("custom", true);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM blob", Integer.class)).isZero();
    }

    @Test
    @DisplayName("기본 제공 제스처는 템플릿이 없고, 그 이름을 커스텀으로 가로챌 수 없으며, npz 없는 저장은 거절된다")
    void cannedHasNoTemplateAndNameIsProtected() {
        long canned = jdbc.queryForObject("SELECT id FROM gesture WHERE name = 'Open_Palm'", Long.class);
        assertThat(service.getOne(canned)).containsEntry("custom", false);
        assertThat(service.customNpzRefs()).isEmpty();
        assertThatThrownBy(() -> service.npzMeta(canned))
                .isInstanceOf(ApiException.class).hasMessageContaining("템플릿이 없습니다");
        assertThatThrownBy(() -> save("Open_Palm", NPZ_A))
                .isInstanceOf(ApiException.class).hasMessageContaining("기본 제공");
        assertThatThrownBy(() -> service.updateNpz(canned, NPZ_A, Sha256.hex(NPZ_A), 1, "STATIC"))
                .isInstanceOf(ApiException.class).hasMessageContaining("기본 제공");
        assertThatThrownBy(() -> service.saveCustom("x", null, null, null, false,
                List.of(new GestureService.Step("scroll.step", Map.of(), null)), null, null, 1, "STATIC"))
                .isInstanceOf(ApiException.class).hasMessageContaining("npz");
    }

    @Test
    @DisplayName("기본 제공 제스처는 기능만 바꿀 수 있다 — 빈 배열은 기능 해제, 이름·라벨·설명은 거절")
    void builtinTakesFunctionOnly() {
        long builtin = jdbc.queryForObject("SELECT id FROM gesture WHERE name = 'Open_Palm'", Long.class);

        service.update(builtin, null, null, null, true,
                List.of(new GestureService.Step("scroll.step", Map.of("dir", "up"), null)));

        assertThat(service.getOne(builtin)).containsEntry("repeatable", true)
                .containsEntry("runnable", true);
        assertThat(service.getOne(builtin).get("steps")).asList().hasSize(1);
        assertThat(jdbc.queryForList("SELECT tool_name, args_json FROM gesture_step WHERE gesture_id = ?",
                builtin)).singleElement().satisfies(step -> assertThat(step)
                        .containsEntry("tool_name", "scroll.step").containsEntry("args_json", "{\"dir\":\"up\"}"));

        // 이름·라벨·설명은 BE 소유다 — 기동 시드가 카탈로그 값으로 되돌리므로 받지 않는다
        assertThatThrownBy(() -> service.update(builtin, "내 손바닥", null, null, null, null))
                .isInstanceOf(ApiException.class).hasMessageContaining("기능 변경만");
        assertThatThrownBy(() -> service.update(builtin, null, "손바닥", null, null, null))
                .isInstanceOf(ApiException.class).hasMessageContaining("기능 변경만");
        verify(agentHub, never()).send(eq("gesture_renamed"), any());

        // 빈 배열 = 기능 해제. 기본 제공 제스처만 허용된다
        service.update(builtin, null, null, null, null, List.of());
        assertThat(service.getOne(builtin).get("steps")).asList().isEmpty();
        assertThat(service.getOne(builtin)).containsEntry("runnable", false);

        long custom = save("손가락 하트", NPZ_A);
        assertThatThrownBy(() -> service.update(custom, null, null, null, null, List.of()))
                .isInstanceOf(ApiException.class).hasMessageContaining("최소 한 단계");
    }

    @Test
    @SuppressWarnings("unchecked")
    @DisplayName("이름 변경·삭제 통지는 id 를 싣고, 삭제하면 템플릿도 목록에서 사라진다 — AI 의 npz 재업로드는 없다")
    void renameAndRemoveCarryId() {
        long a = save("손가락 하트", NPZ_A);

        service.update(a, "하트", null, null, null, null);
        ArgumentCaptor<Map<String, Object>> renamed = ArgumentCaptor.forClass(Map.class);
        verify(agentHub).send(eq("gesture_renamed"), renamed.capture());
        assertThat(renamed.getValue()).containsEntry("id", a)
                .containsEntry("oldName", "손가락 하트").containsEntry("newName", "하트");
        assertThat(service.customNpzRefs()).extracting(r -> r.get("name")).containsExactly("하트");
        assertThat(service.npz(a)).isEqualTo(NPZ_A); // 템플릿은 그대로

        service.removeCustom(a);
        ArgumentCaptor<Map<String, Object>> removed = ArgumentCaptor.forClass(Map.class);
        verify(agentHub).send(eq("gesture_removed"), removed.capture());
        assertThat(removed.getValue()).containsEntry("id", a).containsEntry("name", "하트");
        assertThat(service.customNpzRefs()).isEmpty();
    }

    @Test
    @SuppressWarnings("unchecked")
    @DisplayName("켜기/끄기는 gesture_toggled 에 이어 settings_changed 도 보낸다 — AI 가 후자만 들어도 놓치지 않는다")
    void toggleAlsoNotifiesSettingsChanged() {
        long canned = jdbc.queryForObject("SELECT id FROM gesture WHERE name = 'Open_Palm'", Long.class);

        service.setEnabled(canned, false);

        ArgumentCaptor<Map<String, Object>> toggled = ArgumentCaptor.forClass(Map.class);
        verify(agentHub).send(eq("gesture_toggled"), toggled.capture());
        assertThat(toggled.getValue()).containsEntry("name", "Open_Palm").containsEntry("enabled", false);
        verify(notifier).notifySettingsChanged();
        assertThat(service.disabledNames()).contains("Open_Palm");
    }

    @Test
    @DisplayName("재촬영(updateNpz)은 같은 행의 템플릿·sha256 과 형태(hands·motion)를 함께 교체한다")
    void updateNpzReplacesTemplate() {
        long a = save("손가락 하트", NPZ_A, 2, "DYNAMIC");

        service.updateNpz(a, NPZ_B, Sha256.hex(NPZ_B), 1, "STATIC");

        assertThat(service.npz(a)).isEqualTo(NPZ_B);
        assertThat(service.npzMeta(a).sha256()).isEqualTo(Sha256.hex(NPZ_B));
        assertThat(service.customNpzRefs()).hasSize(1);
        // 한손 정적으로 다시 찍었으면 그 형태가 남는다
        assertThat(service.getOne(a)).containsEntry("hands", 1).containsEntry("motion", "STATIC");
    }

    @Test
    @DisplayName("목록은 hands·motion 으로 걸러지고, 두 축은 blobs.gestures 에도 실린다")
    void listFiltersAndBlobsCarryShape() {
        long twoHandDynamic = save("손가락 하트", NPZ_A, 2, "DYNAMIC");
        save("주먹", NPZ_B, 1, "STATIC");

        assertThat(service.list(null, true, 2, null, false, 0, 20).items())
                .extracting(g -> g.get("id")).containsExactly(twoHandDynamic);
        assertThat(service.list(null, true, null, "DYNAMIC", false, 0, 20).items())
                .extracting(g -> g.get("id")).containsExactly(twoHandDynamic);
        // 픽스처의 canned 1건 + 커스텀 1건이 한손 정적이다
        assertThat(service.list("HAND", null, 1, "STATIC", false, 0, 20).total()).isEqualTo(2);

        assertThat(service.customNpzRefs())
                .anySatisfy(r -> assertThat(r).containsEntry("hands", 2).containsEntry("motion", "DYNAMIC"))
                .anySatisfy(r -> assertThat(r).containsEntry("hands", 1).containsEntry("motion", "STATIC"));
    }

    @Test
    @DisplayName("hands·motion 은 1·2 와 STATIC·DYNAMIC 만 받는다 — SQLite CHECK 를 못 걸어 서비스가 문지기다")
    void shapeValuesAreValidated() {
        assertThatThrownBy(() -> save("셋손", NPZ_A, 3, "STATIC"))
                .isInstanceOf(ApiException.class).hasMessageContaining("hands");
        assertThatThrownBy(() -> save("애매", NPZ_A, 1, "WOBBLY"))
                .isInstanceOf(ApiException.class).hasMessageContaining("motion");
        assertThatThrownBy(() -> service.list(null, null, 9, null, false, 0, 20))
                .isInstanceOf(ApiException.class).hasMessageContaining("hands");
    }
}
