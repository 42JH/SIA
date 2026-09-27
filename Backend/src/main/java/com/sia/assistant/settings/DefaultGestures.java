package com.sia.assistant.settings;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.jdbc.core.JdbcTemplate;

/**
 * 기본 제공 제스처 9종 — 모양만 정의하고 행동은 비워 둔다 (2026-09-11 확정).
 * 어떤 기능을 걸지는 사용자가 제스처 목록에서 지정한다(PUT /api/gestures/{id} 의 steps).
 * 그래서 이 시드는 gesture 행만 만들고 gesture_step 은 한 건도 만들지 않는다.
 * ★옛 시드는 컨텍스트별(video · youtube) 행동이 박힌 매핑 11건(HAND 9 + FACE 2)이었다. 그 행들을
 *   여기서 지우지는 않는다 — 카탈로그에 없는 custom=0 행을 기동마다 지우면, 나중에 내장 목록에서
 *   이름 하나를 뺄 때 사용자가 그 제스처에 걸어 둔 기능이 조용히 사라진다. 개발 중이라 옛 행은
 *   로컬 sia.db 를 지우고 재기동해 없앤다 — 마이그레이션을 따로 두지 않았다.
 *
 * 시드가 마이그레이션 SQL 이 아니라 Java 인 이유는 그대로다: 전체 삭제 복원(WipeService)이 같은
 * 정의를 다시 써야 하고, 시드의 원천을 코드 한 곳에 둔다.
 *
 * 규칙 — DefaultAppTargets 와 같은 결로 "테이블이 비어 있을 때만" 이 아니라 "없는 이름만" 이다:
 *  - 행이 이미 있으면 steps · enabled · repeatable 은 손대지 않는다 (사용자가 지정한 값이다).
 *  - label · description · hands · motion 은 BE 가 소유하므로 카탈로그 값으로 맞춘다.
 *  - 목록에서 빼려면 DELETE 가 아니라 enabled = 0 이다. 지우면 다음 기동에 다시 살아난다.
 *  - 기본 제공 목록에서 은퇴시킬 이름이 생기면 그때 마이그레이션으로 지운다 (기동마다 지우지 않는다 —
 *    사용자가 지정한 기능을 조용히 날릴 수 있는 유일한 경로라서다).
 */
public final class DefaultGestures {

    /** 기본 제공 제스처 한 종 — 모양과 표시 문구만 갖는다. 실행할 도구는 갖지 않는다. */
    record Builtin(String name, String label, String description, String motion) {
    }

    /**
     * 삽입 건수 · 표시 문구를 맞춘 건수 · 커스텀 제스처가 이름을 먼저 차지해 넣지 못한 이름.
     * conflicts 는 옛 시드에 없던 이름(Victory · Pointing_Up · ILoveYou · 스와이프 2종)을
     * 사용자가 커스텀으로 등록해 둔 DB 에서만 나온다 — 그때는 기본 제공 한 종이 목록에 빠진다.
     */
    public record Result(int inserted, int synced, List<String> conflicts) {
    }

    /**
     * 기본 제공 제스처 9종. 이름은 AI 가 gesture_exec 로 보내는 키라 그대로 둔다 (MediaPipe 기본 제스처 7종 +
     * 좌우 스와이프 2종). 전부 한손이고, 스와이프만 동작(DYNAMIC)이다.
     */
    static List<Builtin> all() {
        return List.of(
                new Builtin("Closed_Fist", "주먹 쥐기", "주먹을 꽉 쥔 모양입니다.", "STATIC"),
                new Builtin("Open_Palm", "손바닥 펴기", "손바닥을 활짝 편 모양입니다.", "STATIC"),
                new Builtin("Pointing_Up", "검지 올리기", "검지손가락만 위로 치켜세운 모양입니다.", "STATIC"),
                new Builtin("Thumb_Down", "엄지 내리기", "엄지손가락을 아래로 내린 모양입니다.", "STATIC"),
                new Builtin("Thumb_Up", "엄지 올리기", "엄지손가락을 위로 올린 모양입니다.", "STATIC"),
                new Builtin("Victory", "브이", "검지와 중지를 편 브이 모양입니다.", "STATIC"),
                new Builtin("ILoveYou", "사랑해", "엄지, 검지, 새끼손가락을 편 사랑해 수어 제스처입니다.", "STATIC"),
                new Builtin("Swipe_Left", "왼쪽 스와이프", "손을 왼쪽으로 빠르게 쓸어 넘기는 동작입니다.", "DYNAMIC"),
                new Builtin("Swipe_Right", "오른쪽 스와이프", "손을 오른쪽으로 빠르게 쓸어 넘기는 동작입니다.", "DYNAMIC"));
    }

    /** 없는 이름만 넣고 표시 문구를 맞춘다. 호출자가 트랜잭션을 보장한다. */
    public static Result seedInto(JdbcTemplate jdbc) {
        return seedInto(jdbc, all());
    }

    static Result seedInto(JdbcTemplate jdbc, List<Builtin> builtins) {
        // 기본 제공 자리는 (kind HAND, context NULL, name) 하나다. SQLite 의 UNIQUE 는 NULL 끼리 충돌하지
        // 않으므로(GestureService 주석 참고) 같은 이름의 커스텀이 있어도 INSERT 가 막히지 않는다 —
        // 이름이 겹치면 조회가 갈리므로 여기서 직접 비켜 준다.
        Map<String, Builtin> builtinRows = new HashMap<>();
        Set<String> takenByCustom = new HashSet<>();
        jdbc.query("SELECT name, custom, label, description, motion FROM gesture"
                + " WHERE kind = 'HAND' AND context IS NULL", rs -> {
            String name = rs.getString("name");
            if (rs.getInt("custom") == 1) {
                takenByCustom.add(name);
                return;
            }
            builtinRows.put(name, new Builtin(name, rs.getString("label"), rs.getString("description"),
                    rs.getString("motion")));
        });

        int inserted = 0;
        int synced = 0;
        List<String> conflicts = new ArrayList<>();
        for (Builtin builtin : builtins) {
            Builtin row = builtinRows.get(builtin.name());
            if (row == null) {
                if (takenByCustom.contains(builtin.name())) {
                    conflicts.add(builtin.name());
                    continue;
                }
                // created_at 은 NULL 로 둔다 — 등록일은 사용자가 등록한 커스텀 제스처만 갖는다
                inserted += jdbc.update(
                        "INSERT INTO gesture (custom, kind, context, name, label, description,"
                                + " repeatable, enabled, hands, motion) VALUES (0, 'HAND', NULL, ?, ?, ?, 0, 1, 1, ?)",
                        builtin.name(), builtin.label(), builtin.description(), builtin.motion());
                continue;
            }
            if (row.equals(builtin)) {
                continue;  // 기동마다 같은 값을 다시 쓰지 않는다
            }
            synced += jdbc.update("UPDATE gesture SET label = ?, description = ?, hands = 1, motion = ?"
                            + " WHERE custom = 0 AND kind = 'HAND' AND context IS NULL AND name = ?",
                    builtin.label(), builtin.description(), builtin.motion(), builtin.name());
        }
        return new Result(inserted, synced, List.copyOf(conflicts));
    }

    private DefaultGestures() {
    }
}
