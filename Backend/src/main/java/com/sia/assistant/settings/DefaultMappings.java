package com.sia.assistant.settings;

import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * 기본(canned) 제스처 매핑 11건 — 매핑 원천 테이블(gesture/gesture_step)의 시드.
 * 마이그레이션 SQL 이 아니라 Java 가 넣는다: 도구 목록의 원천은 ToolCatalog(코드) 하나이고,
 * gesture_step.tool_name FK 가 tool 행을 요구하므로 ToolCatalogSync 가 tool 을 만든 뒤에만 넣을 수 있다.
 * 첫 기동은 DefaultMappingBootstrap 이, 전체 삭제 복원은 WipeService 가 이 클래스를 쓴다.
 */
public final class DefaultMappings {

    /** tool 이 null 인 FACE 는 스텝 없이 자리만 만든다 — 확인 응답(예/아니오)은 AI 가 직접 받아
     *  BE 쪽 목적지 도구가 없고, GET /api/gestures?dangling= 이 "실행 대상 없음"으로 정확히 보고한다. */
    private record Seed(String kind, String context, String name, String label,
                        boolean repeatable, String tool, String argsJson,
                        Integer hands, String motion) {

        /** canned HAND 시드는 전부 한손 정적이다 (MediaPipe 기본 제스처). */
        static Seed hand(String context, String name, String label, boolean repeatable,
                         String tool, String argsJson) {
            return new Seed("HAND", context, name, label, repeatable, tool, argsJson, 1, "STATIC");
        }

        /** FACE 는 손 개수·동작 구분이 없어 두 축이 NULL 이다. */
        static Seed face(String name, String label) {
            return new Seed("FACE", null, name, label, false, null, null, null, null);
        }
    }

    private static final List<Seed> ALL = List.of(
            Seed.hand(null, "Open_Palm", "세션 연장", false, "session.extend", "{}"),
            Seed.hand(null, "Thumb_Up", "위로 스크롤", true, "scroll.step", "{\"dir\":\"up\"}"),
            Seed.hand(null, "Thumb_Down", "아래로 스크롤", true, "scroll.step", "{\"dir\":\"down\"}"),
            Seed.hand(null, "Closed_Fist", "재생/일시정지", false, "media.play_pause", "{}"),
            Seed.hand("video", "Open_Palm", "재생/일시정지", false, "media.play_pause", "{}"),
            Seed.hand("video", "Victory", "음소거", false, "media.mute_toggle", "{}"),
            Seed.hand("video", "Thumb_Up", "볼륨 올리기", true, "volume.step", "{\"dir\":\"up\"}"),
            Seed.hand("video", "Thumb_Down", "볼륨 내리기", true, "volume.step", "{\"dir\":\"down\"}"),
            Seed.hand("youtube", "Pointing_Up", "다음 영상", false, "media.next", "{}"),
            Seed.face("brow_raise", "예"),
            Seed.face("smile", "아니오"));

    /** gesture/gesture_step 에 기본 매핑을 넣는다. 호출자가 빈 상태와 트랜잭션을 보장한다. */
    public static int seedInto(JdbcTemplate jdbc) {
        for (Seed seed : ALL) {
            jdbc.update("INSERT INTO gesture (custom, kind, context, name, label, repeatable,"
                            + " hands, motion) VALUES (0, ?, ?, ?, ?, ?, ?, ?)",
                    seed.kind(), seed.context(), seed.name(), seed.label(), seed.repeatable() ? 1 : 0,
                    seed.hands(), seed.motion());
            if (seed.tool() == null) {
                continue;  // gesture_step.tool_name 은 NOT NULL — dangling 시드는 스텝을 만들지 않는다
            }
            Long id = jdbc.queryForObject("SELECT last_insert_rowid()", Long.class);
            jdbc.update("INSERT INTO gesture_step (gesture_id, tool_name, step_no, args_json)"
                            + " VALUES (?, ?, 1, ?)",
                    id, seed.tool(), seed.argsJson());
        }
        return ALL.size();
    }

    private DefaultMappings() {
    }
}
