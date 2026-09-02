package com.sia.assistant.common;

public class ApiException extends RuntimeException {

    public final ErrorCode code;
    public final String detail;

    public ApiException(ErrorCode code, String userMessage) {
        this(code, userMessage, null);
    }

    public ApiException(ErrorCode code, String userMessage, String detail) {
        super(userMessage);
        this.code = code;
        this.detail = detail;
    }
}
