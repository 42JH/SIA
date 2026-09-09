package com.sia.assistant.settings;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ObjectNode;
import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * PUT /api/settings 는 통째 교체지만, <b>알려진 키는 유실될 수 없다</b> —
 * micDevice 하나가 사라지면 이후 프로필의 장비 라벨이 비어 자동 맵핑이 영구히 깨진다.
 * 완전성(fillMissing)과 타입 안전(validate) 두 가지만 강제하고 미지의 키는 건드리지 않는다.
 */
class SettingsSchemaTest {

    private static final ObjectMapper OM = new ObjectMapper();
    private static final String SEED =
            "{\"wakeWord\":\"시아\",\"sessionSeconds\":15,\"autoStart\":true,"
                    + "\"gazeCursor\":false,\"micDevice\":null,\"cameraDevice\":null}";

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
                .containsExactlyInAnyOrder("autoStart", "gazeCursor", "micDevice", "cameraDevice");
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

        assertThat(SettingsSchema.fillMissing(incoming, current, seed())).isEmpty();
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

    private void assertBad(String json, String messagePart) throws Exception {
        assertThatThrownBy(() -> SettingsSchema.validate(obj(json)))
                .isInstanceOfSatisfying(ApiException.class, e -> {
                    assertThat(e.code).isEqualTo(ErrorCode.INVALID_REQUEST);
                    assertThat(e.getMessage()).contains(messagePart);
                });
    }
}
