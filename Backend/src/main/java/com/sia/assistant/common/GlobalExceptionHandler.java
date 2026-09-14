package com.sia.assistant.common;

import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.TypeMismatchException;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageConversionException;
import org.springframework.web.ErrorResponse;
import org.springframework.web.ErrorResponseException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.ServletRequestBindingException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
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

    /** 프레임워크가 상태를 정해 둔 예외(405·415 등) — 그 상태를 유지하고 INVALID_REQUEST 로 표기한다. */
    @ExceptionHandler(ErrorResponseException.class)
    public ResponseEntity<Map<String, Object>> framework(ErrorResponseException e) {
        return invalid(e.getStatusCode().value(), null);
    }

    /**
     * 파라미터·본문 형식 오류는 400 INVALID_REQUEST 다 (API 명세 §0.4).
     * 쿼리 타입 불일치(?page=abc)·필수 파라미터 누락·본문 역직렬화 실패·검증 실패가 여기로 온다 —
     * 이 예외들은 ErrorResponseException 을 상속하지 않아 예전엔 catch-all 로 떨어져 500 이 됐다.
     */
    @ExceptionHandler({TypeMismatchException.class, HttpMessageConversionException.class,
            ServletRequestBindingException.class, MethodArgumentNotValidException.class})
    public ResponseEntity<Map<String, Object>> badRequest(Exception e) {
        String detail = null;
        if (e instanceof MethodArgumentTypeMismatchException m) {
            detail = m.getName();
        } else if (e instanceof MissingServletRequestParameterException m) {
            detail = m.getParameterName();
        }
        return invalid(400, detail);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Map<String, Object>> internal(Exception e) {
        if (e instanceof ErrorResponse er) {
            // 405·406·415 처럼 스프링이 상태를 정해 둔 예외 — 서버 오류가 아니다
            return invalid(er.getStatusCode().value(), null);
        }
        log.error("unhandled", e);
        return ResponseEntity.status(500)
                .body(Map.of("code", "INTERNAL_ERROR", "message", "서버 내부 오류입니다"));
    }

    private static ResponseEntity<Map<String, Object>> invalid(int status, String detail) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("code", "INVALID_REQUEST");
        body.put("message", "요청 형식이 올바르지 않습니다");
        if (detail != null) {
            body.put("detail", detail);
        }
        return ResponseEntity.status(status).body(body);
    }
}
