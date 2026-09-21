package com.sia.assistant.settings;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * PUT /api/settings 는 통째 교체지만, <b>알려진 키는 유실될 수 없다</b> —
 * micDevice 하나가 사라지면 이후 프로필의 장비 라벨이 비어 자동 맵핑이 영구히 깨진다.
 * 완전성(fillMissing)과 타입 안전(validate) 두 가지만 강제하고 미지의 키는 건드리지 않는다.
 */
class SettingsSchemaTest {

    private static final ObjectMapper OM = new ObjectMapper();
    private static final String SEED =
            "{\"wakeWord\":\"시아\",\"sessionSeconds\":15,\"autoStart\":true,"
                    + "\"gazeCursor\":false,\"micDevice\":null,\"cameraDevice\":null,"
                    + "\"micDeviceId\":null,\"cameraDeviceId\":null}";

    private ObjectNode obj(String json) throws Exception {
        return (ObjectNode) OM.readTree(json);
    }

    private JsonNode seed() throws Exception {
        return OM.readTree(SEED);
    }

    @Test
    @DisplayName("빠진 알려진 키는 기존 값으로 채워진다 — 구버전 클라이언트가 micDevice 를 지울 수 없다")
    void missingKeysAreFilledFromCurrent() throws Exception {
        JsonNode current = obj("{\"wakeWord\":\"시아\",\"sessionSeconds\":15,\"autoStart\":true,"
                + "\"gazeCursor\":true,\"micDevice\":\"마이크(Realtek(R) Audio)\",\"cameraDevice\":\"HD Webcam\"}");
        // 옛 FE 가 아는 키만 보냈다 — micDevice·cameraDevice·gazeCursor 를 모른다
        ObjectNode incoming = obj("{\"wakeWord\":\"시아\",\"sessionSeconds\":30}");

        assertThat(SettingsSchema.fillMissing(incoming, current, seed()))
                .containsExactlyInAnyOrder("autoStart", "gazeCursor", "micDevice", "cameraDevice",
                        "micDeviceId", "cameraDeviceId");
        assertThat(incoming.path("micDevice").asText()).isEqualTo("마이크(Realtek(R) Audio)");
        assertThat(incoming.path("cameraDevice").asText()).isEqualTo("HD Webcam");
        assertThat(incoming.path("gazeCursor").asBoolean()).isTrue();
        assertThat(incoming.path("sessionSeconds").asInt()).isEqualTo(30); // 보낸 값은 그대로
    }

    @Test
    @DisplayName("기존 문서에도 없으면 시드 값으로 채운다")
    void missingKeysFallBackToSeed() throws Exception {
        ObjectNode incoming = obj("{\"wakeWord\":\"시아\"}");

        SettingsSchema.fillMissing(incoming, obj("{}"), seed());

        assertThat(incoming.path("sessionSeconds").asInt()).isEqualTo(15);
        assertThat(incoming.path("autoStart").asBoolean()).isTrue();
        assertThat(incoming.path("micDevice").isNull()).isTrue();
    }

    @Test
    @DisplayName("★ 명시적 null 은 덮지 않는다 — micDevice:null 은 '시스템 기본을 쓰겠다'는 의사 표시다")
    void explicitNullIsAnIntentNotAnAbsence() throws Exception {
        JsonNode current = obj("{\"micDevice\":\"USB Mic\",\"cameraDevice\":\"HD Webcam\"}");
        ObjectNode incoming = obj("{\"wakeWord\":\"시아\",\"sessionSeconds\":15,\"autoStart\":true,"
                + "\"gazeCursor\":false,\"micDevice\":null,\"cameraDevice\":\"HD Webcam\"}");

        // 이 문서에 없는 id 키 2개는 시드에서 채워지고, 명시한 micDevice:null 은 그대로 남는다
        assertThat(SettingsSchema.fillMissing(incoming, current, seed()))
                .containsExactlyInAnyOrder("micDeviceId", "cameraDeviceId");
        assertThat(incoming.path("micDevice").isNull()).isTrue();
    }

    @Test
    @DisplayName("미지의 키는 보정도 검사도 하지 않는다 — settings 는 여전히 자유 JSON 이다")
    void unknownKeysPassThrough() throws Exception {
        ObjectNode incoming = obj("{\"wakeWord\":\"시아\",\"previewMirror\":true,\"theme\":{\"a\":1}}");

        SettingsSchema.fillMissing(incoming, obj("{}"), seed());
        SettingsSchema.validate(incoming);

        assertThat(incoming.path("previewMirror").asBoolean()).isTrue();
        assertThat(incoming.path("theme").path("a").asInt()).isEqualTo(1);
    }

    @Test
    @DisplayName("알려진 키의 타입이 틀리면 저장 전에 INVALID_REQUEST 로 끊는다")
    void wrongTypesAreRejected() throws Exception {
        assertBad("{\"wakeWord\":\"\"}", "호출명");
        assertBad("{\"wakeWord\":42}", "호출명");
        assertBad("{\"sessionSeconds\":0}", "세션 유지 시간");
        assertBad("{\"sessionSeconds\":\"15\"}", "세션 유지 시간");
        assertBad("{\"autoStart\":\"true\"}", "자동 실행");
        assertBad("{\"gazeCursor\":1}", "시선 커서");
        assertBad("{\"micDevice\":123}", "마이크");
        assertBad("{\"cameraDevice\":\"  \"}", "카메라");
        assertBad("{\"micDeviceId\":123}", "마이크 장치 ID");
        assertBad("{\"cameraDeviceId\":\"  \"}", "카메라 장치 ID");
    }

    @Test
    @DisplayName("★ 새 호출어는 완성된 한글만 — 자모 · 영문 · 숫자 · 공백은 AI 감지 모델이 받지 못한다")
    void newWakeWordMustBeCompleteHangul() {
        SettingsSchema.validateWakeWord("시아야");
        SettingsSchema.validateWakeWord("우리집비서");

        assertBadWord("시아ㅇ", "완성된 한글");     // 자모 단독
        assertBadWord("ㅅㅣ아", "완성된 한글");
        assertBadWord("Sia야", "완성된 한글");
        assertBadWord("시아 야", "완성된 한글");    // 공백 — 다듬기는 FE 몫이다
        assertBadWord("시아야!", "완성된 한글");
        assertBadWord("시아22", "완성된 한글");
        assertThatThrownBy(() -> SettingsSchema.validateWakeWord("  ")).isInstanceOf(ApiException.class);
        assertThatThrownBy(() -> SettingsSchema.validateWakeWord(null)).isInstanceOf(ApiException.class);
    }

    @Test
    @DisplayName("★ 새 호출어는 2~8글자다 — 짧으면 생활 소음에 걸리고 길면 한 번에 부르기 어렵다")
    void newWakeWordLengthIsBounded() {
        SettingsSchema.validateWakeWord("시아");                // 2 — 하한
        SettingsSchema.validateWakeWord("시아야");
        SettingsSchema.validateWakeWord("우리집비서야호출");       // 8 — 상한

        assertBadWord("아", "2~8글자");
        assertBadWord("우리집비서야호출어", "2~8글자");            // 9
    }

    @Test
    @DisplayName("★ 설정 문서 검사는 호출어 글자 규칙을 걸지 않는다 — PUT 으로 못 바꾸는 값에 규칙을 걸면 옛 DB 가 잠긴다")
    void documentValidationLeavesStoredWakeWordAlone() throws Exception {
        // 옛 규칙은 "비어 있지 않은 문자열" 이라 무엇이든 저장돼 있을 수 있다.
        // 이걸 400 으로 막으면 호출어와 무관한 설정도 저장할 수 없고, 푸는 길인 재등록까지 함께 막힌다
        SettingsSchema.validate(obj("{\"wakeWord\":\"sia\",\"sessionSeconds\":15}"));
        SettingsSchema.validate(obj("{\"wakeWord\":\"시\",\"sessionSeconds\":15}"));
        assertBad("{\"wakeWord\":\"\"}", "호출명");             // 타입 · 공백 검사는 그대로다
    }

    @Test
    @DisplayName("세션 유지 시간은 사용자가 바꿀 수 있다 — 1 이상 정수면 통과")
    void sessionSecondsIsChangeable() throws Exception {
        SettingsSchema.validate(obj("{\"sessionSeconds\":1}"));
        SettingsSchema.validate(obj("{\"sessionSeconds\":60}"));
        SettingsSchema.validate(obj("{\"sessionSeconds\":300}"));
    }

    @Test
    @DisplayName("정상 문서는 통과한다 — 장치 이름은 OS 원문 문자열이거나 null 이다")
    void validDocumentPasses() throws Exception {
        SettingsSchema.validate(obj(SEED));
        SettingsSchema.validate(obj("{\"wakeWord\":\"시아\",\"sessionSeconds\":15,\"autoStart\":false,"
                + "\"gazeCursor\":true,\"micDevice\":\"마이크(Realtek(R) Audio)\",\"cameraDevice\":\"HD Webcam\"}"));
    }

    @Test
    @DisplayName("장치 ID 는 GET /api/devices 가 준 문자열이거나 null 이다 — 존재 여부는 검사하지 않는다")
    void deviceIdsAreStoredAsGiven() throws Exception {
        // 역슬래시가 JSON·Java 양쪽에서 두 번 이스케이프되는 걸 피해 노드를 직접 만든다
        ObjectNode doc = OM.createObjectNode();
        doc.put("micDeviceId", "{0.0.1.00000000}.{2b1c7d55-0e4f-4a1f-9c1e-3f0b8a2d6e11}");
        doc.put("cameraDeviceId",
                "\\\\?\\usb#vid_046d&pid_082d&mi_00#7&1a2b3c4d&0&0000#{e5323777-f976-4f5b-9b55-b94699c46e44}");

        // 지금 안 꽂혀 있는 장치의 id 여도 저장된다 — 여는 쪽(AI)이 판단할 몫이다
        SettingsSchema.validate(doc);
        SettingsSchema.validate(obj("{\"micDeviceId\":null,\"cameraDeviceId\":null}"));
    }

    private void assertBadWord(String wakeWord, String messagePart) {
        assertThatThrownBy(() -> SettingsSchema.validateWakeWord(wakeWord))
                .isInstanceOfSatisfying(ApiException.class, e -> {
                    assertThat(e.code).isEqualTo(ErrorCode.INVALID_REQUEST);
                    assertThat(e.getMessage()).contains(messagePart);
                });
    }

    private void assertBad(String json, String messagePart) throws Exception {
        assertThatThrownBy(() -> SettingsSchema.validate(obj(json)))
                .isInstanceOfSatisfying(ApiException.class, e -> {
                    assertThat(e.code).isEqualTo(ErrorCode.INVALID_REQUEST);
                    assertThat(e.getMessage()).contains(messagePart);
                });
    }
}
