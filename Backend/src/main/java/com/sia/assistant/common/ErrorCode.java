package com.sia.assistant.common;

import org.springframework.http.HttpStatus;

public enum ErrorCode {

    SETTINGS_STALE(HttpStatus.CONFLICT),
    CALIB_RESOLUTION_MISMATCH(HttpStatus.CONFLICT),
    APP_NOT_REGISTERED(HttpStatus.BAD_REQUEST),
    APP_PATH_INVALID(HttpStatus.BAD_REQUEST),
    REF_NOT_FOUND(HttpStatus.BAD_REQUEST),
    SESSION_REQUIRED(HttpStatus.CONFLICT),
    // CONFIRM_REQUIRED · CONFIRM_NOT_PENDING 은 확인 게이트와 함께 삭제됐다 (2026-09-01).
    // 동의는 AI 가 도구를 부르기 전에 받는다 — BE 에 "대기" 상태는 없다 (API.md §5).
    ELEVATED_WINDOW(HttpStatus.FORBIDDEN),
    // 권한이 아니라 Windows 의 포그라운드 잠금에 막힌 것 — 관리자 권한 창과 갈라 보고한다 (2026-09-17)
    FOREGROUND_BLOCKED(HttpStatus.FORBIDDEN),
    BLOB_NOT_FOUND(HttpStatus.NOT_FOUND),
    PROFILE_NOT_FOUND(HttpStatus.NOT_FOUND),
    PROFILE_LIMIT(HttpStatus.CONFLICT),
    PROFILE_IN_USE(HttpStatus.CONFLICT),
    FILE_NOT_FOUND(HttpStatus.NOT_FOUND),
    GESTURE_NOT_FOUND(HttpStatus.NOT_FOUND),
    MODEL_DOWNLOAD_FAILED(HttpStatus.BAD_GATEWAY),
    EXTENSION_UNAVAILABLE(HttpStatus.SERVICE_UNAVAILABLE),
    INVALID_REQUEST(HttpStatus.BAD_REQUEST),
    UNAUTHORIZED(HttpStatus.UNAUTHORIZED),
    NOT_FOUND(HttpStatus.NOT_FOUND),
    INTERNAL_ERROR(HttpStatus.INTERNAL_SERVER_ERROR);

    public final HttpStatus status;

    ErrorCode(HttpStatus status) {
        this.status = status;
    }
}
