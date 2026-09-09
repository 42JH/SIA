package com.sia.assistant.settings;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import java.util.ArrayList;
import java.util.List;

/**
 * 설정 JSON 의 <b>알려진 키</b>만 정의한다 — BE·AI 가 실제로 읽어서 동작이 달라지는 값들이다.
 *
 * <p>settings_json 은 여전히 자유 JSON 이고 미지의 키는 그대로 통과한다(FE 가 UI 상태를 얹을 수 있다).
 * 다만 아래 키들은 <b>PUT 이 통째 교체라는 이유로 조용히 사라지면 안 된다</b> —
 * 예를 들어 {@code micDevice} 가 유실되면 이후 등록되는 보이스 프로필의 장비 라벨이 비고,
 * 장비 교체 자동 맵핑(POST /api/devices/remap)이 영구히 후보를 못 찾는다.
 * 그래서 두 가지만 강제한다:
 * <ol>
 *   <li><b>완전성</b> — 본문에 없는 알려진 키는 기존 값(없으면 시드 값)으로 채운다 ({@link #fillMissing}).</li>
 *   <li><b>타입 안전</b> — 알려진 키의 타입이 틀리면 저장하지 않고 INVALID_REQUEST ({@link #validate}).</li>
 * </ol>
 * 미지의 키는 검사도 보정도 하지 않는다.
 */
final class SettingsSchema {

    /**
     * 세션 유지 시간의 기본값(초) — 시드 값이자, 문서에서 읽지 못했을 때의 폴백이다.
     * 사용자가 바꿀 수 있고(1 이상 정수), 변경은 <b>다음 세션 개시·갱신부터</b> 적용된다
     * ({@code SessionService} 가 매번 새로 읽는다).
     */
    static final int DEFAULT_SESSION_SECONDS = 15;

    /** 값의 허용 형태. */
    private enum Kind {
        /** 비어 있지 않은 문자열. */
        TEXT,
        /** 1 이상의 정수. */
        POSITIVE_INT,
        /** true / false. */
        BOOLEAN,
        /** 장치 이름 문자열 또는 null(= 시스템 기본 장치를 따른다). */
        DEVICE_NAME
    }

    private record Key(String name, Kind kind, String label) {
    }

    private static final List<Key> KEYS = List.of(
            new Key("wakeWord", Kind.TEXT, "호출명"),
            new Key("sessionSeconds", Kind.POSITIVE_INT, "세션 유지 시간"),
            new Key("autoStart", Kind.BOOLEAN, "컴퓨터 시작 시 자동 실행"),
            new Key("gazeCursor", Kind.BOOLEAN, "시선 커서 표시"),
            new Key("micDevice", Kind.DEVICE_NAME, "마이크"),
            new Key("cameraDevice", Kind.DEVICE_NAME, "카메라"));

    /**
     * 본문에 없는 알려진 키를 기존 값 → 시드 값 순으로 채운다.
     * ★ 명시적 {@code null} 은 "있는 값"으로 본다 — {@code micDevice: null} 은 시스템 기본을
     * 쓰겠다는 <b>의사 표시</b>라서 덮으면 안 된다. 빠진 키(missing)만 채운다.
     *
     * @return 채워 넣은 키 이름들 (호출자가 경고 로그로 남긴다). 비어 있으면 완전한 문서였다는 뜻
     */
    static List<String> fillMissing(ObjectNode target, JsonNode current, JsonNode seed) {
        List<String> filled = new ArrayList<>();
        for (Key key : KEYS) {
            if (target.has(key.name())) {
                continue;
            }
            JsonNode fallback = pick(current, seed, key.name());
            if (fallback == null) {
                continue; // 기존·시드 어디에도 없다 — 스키마가 앞서 나간 상태. validate 가 판단한다
            }
            target.set(key.name(), fallback.deepCopy());
            filled.add(key.name());
        }
        return filled;
    }

    /** 알려진 키의 타입 검사. 위반 시 저장 전에 INVALID_REQUEST 로 끊는다. */
    static void validate(JsonNode settings) {
        for (Key key : KEYS) {
            JsonNode v = settings.path(key.name());
            if (v.isMissingNode()) {
                continue; // fillMissing 이 채우지 못한 경우 — 값 없이 두는 것까지는 막지 않는다
            }
            switch (key.kind()) {
                case TEXT -> {
                    if (!v.isTextual() || v.asText().isBlank()) {
                        throw bad(key, "비어 있지 않은 문자열이어야 합니다");
                    }
                }
                case POSITIVE_INT -> {
                    if (!v.isIntegralNumber() || v.asInt() < 1) {
                        throw bad(key, "1 이상의 정수여야 합니다");
                    }
                }
                case BOOLEAN -> {
                    if (!v.isBoolean()) {
                        throw bad(key, "true 또는 false 여야 합니다");
                    }
                }
                case DEVICE_NAME -> {
                    // null = 시스템 기본 장치. 문자열이면 OS 가 보고한 장치 이름 원문이어야 한다
                    if (!v.isNull() && (!v.isTextual() || v.asText().isBlank())) {
                        throw bad(key, "OS 가 보고하는 장치 이름 문자열이거나 null(시스템 기본)이어야 합니다");
                    }
                }
                default -> throw new IllegalStateException("알 수 없는 설정 타입: " + key.kind());
            }
        }
    }

    private static JsonNode pick(JsonNode current, JsonNode seed, String name) {
        if (current != null && current.has(name)) {
            return current.get(name);
        }
        if (seed != null && seed.has(name)) {
            return seed.get(name);
        }
        return null;
    }

    private static ApiException bad(Key key, String requirement) {
        return new ApiException(ErrorCode.INVALID_REQUEST,
                key.label() + "(" + key.name() + ") 설정은 " + requirement);
    }

    private SettingsSchema() {
    }
}
