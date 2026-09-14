package com.sia.assistant.common;

/**
 * 콘솔 로그용 페이로드 절단. 사람이 읽는 줄이라 {@link JsonTruncate} 와 달리 유효 JSON 을 유지하지 않는다 —
 * 앞 300자만 남기고 원본 길이를 붙인다. WS 봉투(BaseHub)와 도구 인자(ToolGate)가 같은 형식을 쓴다.
 */
public final class LogPreview {

    /** 콘솔에 남기는 페이로드 미리보기 상한(문자). */
    public static final int MAX = 300;

    private LogPreview() {
    }

    public static String of(String text) {
        if (text == null) {
            return "{}";
        }
        if (text.length() <= MAX) {
            return text;
        }
        int cut = MAX;
        // 서로게이트 쌍을 반으로 자르면 짝 잃은 문자가 남는다
        if (Character.isHighSurrogate(text.charAt(cut - 1))) {
            cut--;
        }
        return text.substring(0, cut) + "…(" + text.length() + "자)";
    }
}
