package com.sia.assistant.settings;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Path;
import java.util.List;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;

/**
 * 기본 제공 제스처 시드 규칙 — 없는 이름만 넣고, 사용자가 지정한 기능(steps)·켜기/끄기는 건드리지 않는다.
 * 표시 문구(label·description·motion)는 BE 소유라 기동마다 카탈로그 값으로 맞춘다.
 */
class DefaultGesturesTest {

    private SingleConnectionDataSource ds;
    private JdbcTemplate jdbc;

    @BeforeEach
    void setUp(@TempDir Path dir) {
        ds = new SingleConnectionDataSource("jdbc:sqlite:" + dir.resolve("builtin-gestures-test.db"), true);
        Flyway.configure().dataSource(ds).locations("classpath:db/migration").load().migrate();
        jdbc = new JdbcTemplate(ds);
    }

    @AfterEach
    void tearDown() {
        ds.destroy();
    }

    @Test
    @DisplayName("빈 테이블에 기본 제공 제스처 9종이 들어간다 — 컨텍스트 없는 한손 HAND, 스텝 0건, 스와이프만 동작")
    void seedsNineShapesWithoutSteps() {
        DefaultGestures.Result result = DefaultGestures.seedInto(jdbc);

        assertThat(result.inserted()).isEqualTo(9);
        assertThat(result.synced()).isZero();
        assertThat(result.conflicts()).isEmpty();
        assertThat(jdbc.queryForList("SELECT name FROM gesture ORDER BY id", String.class))
                .containsExactly("Closed_Fist", "Open_Palm", "Pointing_Up", "Thumb_Down", "Thumb_Up",
                        "Victory", "ILoveYou", "Swipe_Left", "Swipe_Right");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM gesture_step", Integer.class)).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM gesture WHERE custom = 0 AND kind = 'HAND'"
                + " AND context IS NULL AND hands = 1 AND enabled = 1 AND repeatable = 0"
                + " AND created_at IS NULL AND npz IS NULL", Integer.class)).isEqualTo(9);
        assertThat(jdbc.queryForList("SELECT name FROM gesture WHERE motion = 'DYNAMIC' ORDER BY name",
                String.class)).containsExactly("Swipe_Left", "Swipe_Right");
        assertThat(jdbc.queryForObject("SELECT label FROM gesture WHERE name = 'Open_Palm'", String.class))
                .isEqualTo("손바닥 펴기");
    }

    @Test
    @DisplayName("두 번째 기동은 아무것도 넣지 않고, 사용자가 지정한 기능·켜기/끄기를 그대로 둔다")
    void keepsUserAssignedFunctionOnReseed() {
        DefaultGestures.seedInto(jdbc);
        long openPalm = jdbc.queryForObject("SELECT id FROM gesture WHERE name = 'Open_Palm'", Long.class);
        jdbc.update("INSERT INTO tool (name, description, input_schema_json, session_required,"
                + " confirm_required, available, synced_at) VALUES ('session.extend', 'd', '{}', 1, 0, 1, '')");
        jdbc.update("INSERT INTO gesture_step (gesture_id, tool_name, step_no, args_json)"
                + " VALUES (?, 'session.extend', 1, '{}')", openPalm);
        jdbc.update("UPDATE gesture SET enabled = 0, repeatable = 1 WHERE id = ?", openPalm);

        DefaultGestures.Result result = DefaultGestures.seedInto(jdbc);

        assertThat(result.inserted()).isZero();
        assertThat(result.synced()).isZero();
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM gesture", Integer.class)).isEqualTo(9);
        assertThat(jdbc.queryForObject("SELECT tool_name FROM gesture_step WHERE gesture_id = ?",
                String.class, openPalm)).isEqualTo("session.extend");
        assertThat(jdbc.queryForObject("SELECT enabled || '/' || repeatable FROM gesture WHERE id = ?",
                String.class, openPalm)).isEqualTo("0/1");
    }

    @Test
    @DisplayName("표시 문구가 어긋난 옛 행은 카탈로그 값으로 맞춰진다 — 라벨·설명·형태는 BE 소유다")
    void syncsDisplayFieldsOfExistingRows() {
        jdbc.update("INSERT INTO gesture (custom, kind, context, name, label, description, repeatable,"
                + " enabled, hands, motion) VALUES (0, 'HAND', NULL, 'Open_Palm', '세션 연장', NULL, 0, 1, 1, 'STATIC')");

        DefaultGestures.Result result = DefaultGestures.seedInto(jdbc);

        assertThat(result.inserted()).isEqualTo(8);
        assertThat(result.synced()).isEqualTo(1);
        assertThat(jdbc.queryForList("SELECT label, description FROM gesture WHERE name = 'Open_Palm'"))
                .singleElement()
                .satisfies(row -> assertThat(row).containsEntry("label", "손바닥 펴기")
                        .containsEntry("description", "손바닥을 활짝 편 모양입니다."));
    }

    @Test
    @DisplayName("같은 이름의 커스텀 제스처가 있으면 그 한 종만 비켜 준다 — 이름이 겹치면 실행 조회가 갈린다")
    void stepsAsideWhenCustomTookTheName() {
        jdbc.update("INSERT INTO gesture (custom, kind, context, name, label, repeatable, enabled,"
                + " hands, motion) VALUES (1, 'HAND', NULL, 'Victory', '브이', 0, 1, 1, 'STATIC')");

        DefaultGestures.Result result = DefaultGestures.seedInto(jdbc);

        assertThat(result.inserted()).isEqualTo(8);
        assertThat(result.conflicts()).containsExactly("Victory");
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM gesture WHERE name = 'Victory'",
                Integer.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT custom FROM gesture WHERE name = 'Victory'",
                Integer.class)).isEqualTo(1);
    }

    @Test
    @DisplayName("카탈로그에 없는 옛 행은 지우지 않는다 — 그 정리는 로컬 sia.db 삭제로 한다 (README)")
    void leavesRowsOutsideCatalogUntouched() {
        // 옛 시드의 모양: 컨텍스트별 캔드 매핑 + FACE. 기동 시드가 지우는 대상이 아니다 —
        // 매 기동 지우면 나중에 내장 목록에서 이름을 뺄 때 사용자가 지정한 기능까지 날아간다.
        jdbc.update("INSERT INTO gesture (custom, kind, context, name, label, repeatable, enabled,"
                + " hands, motion) VALUES (0, 'HAND', 'video', 'Open_Palm', '재생/일시정지', 0, 1, 1, 'STATIC')");
        jdbc.update("INSERT INTO gesture (custom, kind, context, name, label, repeatable, enabled)"
                + " VALUES (0, 'FACE', NULL, 'brow_raise', '예', 0, 1)");

        DefaultGestures.Result result = DefaultGestures.seedInto(jdbc);

        assertThat(result.inserted()).isEqualTo(9);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM gesture", Integer.class)).isEqualTo(11);
        assertThat(jdbc.queryForObject("SELECT COUNT(*) FROM gesture WHERE context = 'video'"
                + " OR kind = 'FACE'", Integer.class)).isEqualTo(2);
    }

    @Test
    @DisplayName("카탈로그는 이름이 겹치지 않는 9종이다 — 이름이 AI 의 gesture_exec 키다")
    void catalogNamesAreUnique() {
        List<DefaultGestures.Builtin> all = DefaultGestures.all();

        assertThat(all).hasSize(9).extracting(DefaultGestures.Builtin::name).doesNotHaveDuplicates();
        assertThat(all).allSatisfy(builtin -> assertThat(builtin.motion()).isIn("STATIC", "DYNAMIC"));
        assertThat(all).allSatisfy(builtin -> assertThat(builtin.label()).isNotBlank());
        assertThat(all).allSatisfy(builtin -> assertThat(builtin.description()).isNotBlank());
    }
}
