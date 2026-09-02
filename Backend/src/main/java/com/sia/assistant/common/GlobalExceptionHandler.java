package com.sia.assistant.common;

import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.web.ErrorResponseException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.servlet.resource.NoResourceFoundException;

@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<Map<String, Object>> api(ApiException e) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("code", e.code.name());
        body.put("message", e.getMessage());
        if (e.detail != null) {
            body.put("detail", e.detail);
        }
        return ResponseEntity.status(e.code.status).body(body);
    }

    /** catch-all 이 삼키면 MCP Inspector 의 /.well-known/** 탐색이 500 을 받고 멈춘다. */
    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<Map<String, Object>> notFound(NoResourceFoundException e) {
        return ResponseEntity.status(404)
                .body(Map.of("code", "NOT_FOUND", "message", "존재하지 않는 경로입니다"));
    }

    @ExceptionHandler(ErrorResponseException.class)
    public ResponseEntity<Map<String, Object>> framework(ErrorResponseException e) {
        return ResponseEntity.status(e.getStatusCode())
                .body(Map.of("code", "INVALID_REQUEST", "message", "요청 형식이 올바르지 않습니다"));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> internal(Exception e) {
        log.error("unhandled", e);
        return ResponseEntity.status(500)
                .body(Map.of("code", "INTERNAL_ERROR", "message", "서버 내부 오류입니다"));
    }
}
