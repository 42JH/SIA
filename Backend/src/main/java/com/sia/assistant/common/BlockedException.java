package com.sia.assistant.common;

/** 정책 게이트가 막은 것 — ToolGate 가 outcome=BLOCKED 로 기록한다. */
public class BlockedException extends ApiException {

    public BlockedException(ErrorCode code, String userMessage) {
        super(code, userMessage);
    }

    public BlockedException(ErrorCode code, String userMessage, String detail) {
        super(code, userMessage, detail);
    }
}
