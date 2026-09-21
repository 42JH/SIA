package com.sia.assistant.settings;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import java.util.ArrayList;
import java.util.List;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * 설정 JSON 의 <b>알려진 키</b>만 정의한다 — BE·AI 가 실제로 읽어서 동작이 달라지는 값들이다.
 *
 * <p>settings_json 은 여전히 자유 JSON 이고 미지의 키는 그대로 통과한다(FE 가 UI 상태를 얹을 수 있다).
 * 다만 아래 키들은 <b>PUT 이 통째 교체라는 이유로 조용히 사라지면 안 된다</b> —
 * 예를 들어 {@code micDevice} 가 유실되면 이후 등록되는 보이스 프로필의 장비 라벨이 비고,
 * {@code micDeviceId} 가 유실되면 AI 가 사용자가 고른 마이크 대신 시스템 기본 장치를 연다.
 * 앞의 것은 프로필 맵핑용 "이름", 뒤의 것은 실제로 장치를 여는 "식별자"로 역할이 다르다.
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

    /** 호출어 글자 수 — 3자 미만은 생활 소음에 걸리고, 길면 한 번에 부르기 어렵다. */
    static final int WAKE_WORD_MIN = 3;
    static final int WAKE_WORD_MAX = 6;

    /** 값의 허용 형태. */
    private enum Kind {
        /** 비어 있지 않은 문자열. */
        TEXT,
        /** 1 이상의 정수. */
        POSITIVE_INT,
        /** true / false. */
        BOOLEAN,
        /** 장치 이름 문자열 또는 null(= 시스템 기본 장치를 따른다). */
        DEVICE_NAME,
        /** OS 장치 식별자 문자열 또는 null. 이름과 달리 같은 모델이 여러 대여도 겹치지 않는다. */
        DEVICE_ID
    }

    private record Key(String name, Kind kind, String label) {
    }

    private static final List<Key> KEYS = List.of(
            new Key("wakeWord", Kind.TEXT, "호출명"),
            new Key("sessionSeconds", Kind.POSITIVE_INT, "세션 유지 시간"),
            new Key("autoStart", Kind.BOOLEAN, "컴퓨터 시작 시 자동 실행"),
            new Key("gazeCursor", Kind.BOOLEAN, "시선 커서 표시"),
            new Key("micDevice", Kind.DEVICE_NAME, "마이크"),
            new Key("cameraDevice", Kind.DEVICE_NAME, "카메라"),
            new Key("micDeviceId", Kind.DEVICE_ID, "마이크 장치 ID"),
            new Key("cameraDeviceId", Kind.DEVICE_ID, "카메라 장치 ID"));

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
                case DEVICE_ID -> {
                    // GET /api/devices 가 준 id 를 그대로 돌려받는다. 존재 여부는 검사하지 않는다 —
                    // 뽑혀 있는 장치를 저장해 둘 수도 있고, 그 판단은 실제로 장치를 여는 AI 몫이다
                    if (!v.isNull() && (!v.isTextual() || v.asText().isBlank())) {
                        throw bad(key, "GET /api/devices 가 준 장치 식별자 문자열이거나 null(시스템 기본)이어야 합니다");
                    }
                }
                default -> throw new IllegalStateException("알 수 없는 설정 타입: " + key.kind());
            }
        }
    }

    /**
     * 호출어 한 개를 검사한다 — 설정 문서가 아니라 <b>새로 정해지는 단어</b>용이다
     * ({@code wakeword_enroll_start} 의 후보와 {@code SettingsService.commitWakeWord} 의 확정값).
     * 등록을 시작하기 전에 걸러야 사용자가 5번을 다 부르고 나서 저장 단계에서 거절당하는 일이 없다.
     *
     * <p>★ 이 규칙을 {@link #validate}(설정 문서)에 넣지 않는 이유 — PUT 은 호출어를 바꿀 수 없으므로
     * 거기서 글자 규칙을 강제하면, 규칙이 생기기 전에 저장된 호출어(예: 2글자 "시아")를 가진 DB 는
     * 호출어와 무관한 설정 하나를 바꿀 때마다 400 을 맞는다. 규칙은 값이 새로 들어오는 길목에서만 건다.
     *
     * @throws ApiException 완성된 한글 3~6글자가 아니면 INVALID_REQUEST
     */
    static void validateWakeWord(String wakeWord) {
        Key key = KEYS.stream().filter(k -> k.name().equals("wakeWord")).findFirst().orElseThrow();
        if (wakeWord == null || wakeWord.isBlank()) {
            throw bad(key, "비어 있지 않은 문자열이어야 합니다");
        }
        if (!isCompleteHangul(wakeWord)) {
            throw bad(key, "완성된 한글로만 이루어져야 합니다 (예: \"시아야\")."
                    + " 자모 · 영문 · 숫자 · 기호 · 공백은 쓸 수 없습니다");
        }
        int letters = wakeWord.codePointCount(0, wakeWord.length());
        if (letters < WAKE_WORD_MIN || letters > WAKE_WORD_MAX) {
            throw bad(key, WAKE_WORD_MIN + "~" + WAKE_WORD_MAX + "글자여야 합니다 (지금 " + letters + "글자)");
        }
    }

    /**
     * 완성형 한글 음절(U+AC00 가 ~ U+D7A3 힣)로만 이루어졌는지.
     * 자모 단독(ㄱ · ㅏ) · 영문 · 숫자 · 기호는 물론 <b>공백도 허용하지 않는다</b> —
     * 앞뒤 공백을 BE 가 말없이 다듬으면 사용자가 저장한 값과 감지 대상이 달라진다. 다듬기는 FE 몫이다.
     */
    private static boolean isCompleteHangul(String s) {
        return s.codePoints().allMatch(cp -> cp >= 0xAC00 && cp <= 0xD7A3);
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
