package com.sia.assistant.common;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 절단의 계약은 "짧아진다"가 아니라 <b>"짧아져도 파싱된다"</b>이다.
 * 옛 substring 절단은 args_json 을 깨진 JSON 으로 만들어 소비자의 파싱을 터뜨렸다.
 */
class JsonTruncateTest {

    private final ObjectMapper om = new ObjectMapper();

    @Test
    @DisplayName("한도 이내면 손대지 않는다")
    void shortValuePassesThrough() {
        assertThat(JsonTruncate.toFit(om, "{\"dir\":\"up\"}", 500)).isEqualTo("{\"dir\":\"up\"}");
        assertThat(JsonTruncate.toFit(om, null, 500)).isNull();
    }

    @Test
    @DisplayName("넘치면 한도 이내의 유효한 JSON 이 되고 원본 길이가 남는다")
    void longValueBecomesValidJson() throws Exception {
        String original = "{\"content\":\"" + "x".repeat(2000) + "\"}";

        String out = JsonTruncate.toFit(om, original, 500);

        assertThat(out.length()).isLessThanOrEqualTo(500);
        assertThat(om.readTree(out).get("_truncated").asInt()).isEqualTo(original.length());
        assertThat(om.readTree(out).get("_preview").asText()).isNotEmpty();
    }

    @Test
    @DisplayName("이스케이프가 폭발하는 입력도 한도를 넘지 않는다")
    void escapeHeavyValueStillFits() {
        // 따옴표·역슬래시·개행은 JSON 문자열에서 2자로, 제어문자는 6자로 늘어난다
        String original = "{\"a\":\"" + "\"\\\n\t".repeat(400) + "\"}";

        String out = JsonTruncate.toFit(om, original, 500);

        assertThat(out.length()).isLessThanOrEqualTo(500);
        assertThatCode(() -> om.readTree(out)).doesNotThrowAnyException();
    }

    @Test
    @DisplayName("서로게이트 쌍을 반으로 자르지 않는다 — 짝 잃은 문자가 남으면 안 된다")
    void doesNotSplitSurrogatePair() throws Exception {
        String original = "{\"a\":\"" + "😀".repeat(500) + "\"}";

        String out = JsonTruncate.toFit(om, original, 500);

        assertThat(out.length()).isLessThanOrEqualTo(500);
        String preview = om.readTree(out).get("_preview").asText();
        assertThat(preview).isNotEmpty();
        assertThat(Character.isHighSurrogate(preview.charAt(preview.length() - 1))).isFalse();
    }

    @Test
    @DisplayName("미리보기조차 못 담을 만큼 한도가 작아도 파싱되는 값을 준다")
    void tinyLimitStillParses() {
        String out = JsonTruncate.toFit(om, "{\"a\":\"" + "x".repeat(100) + "\"}", 20);

        assertThat(out.length()).isLessThanOrEqualTo(20);
        assertThatCode(() -> om.readTree(out)).doesNotThrowAnyException();
    }
}
