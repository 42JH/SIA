package com.sia.assistant.common;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.TypeMismatchException;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageConversionException;
import org.springframework.web.ErrorResponseException;
import org.springframework.web.HttpRequestMethodNotSupportedException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

class GlobalExceptionHandlerTest {

    private final GlobalExceptionHandler handler = new GlobalExceptionHandler();

    @Test
    @DisplayName("ApiException 은 ErrorCode 의 상태 코드와 {code, message} 본문으로 변환된다")
    void apiExceptionMapsToErrorCodeStatus() {
        ResponseEntity<Map<String, Object>> res =
                handler.api(new ApiException(ErrorCode.GESTURE_NOT_FOUND, "제스처가 없습니다"));

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
        assertThat(res.getBody())
                .containsEntry("code", "GESTURE_NOT_FOUND")
                .containsEntry("message", "제스처가 없습니다")
                .doesNotContainKey("detail");
    }

    @Test
    @DisplayName("detail 이 있으면 본문에 포함된다")
    void detailIsIncludedWhenPresent() {
        ResponseEntity<Map<String, Object>> res =
                handler.api(new ApiException(ErrorCode.APP_PATH_INVALID, "경로가 잘못되었습니다", "C:\\nope.exe"));

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(res.getBody()).containsEntry("detail", "C:\\nope.exe");
    }

    @Test
    @DisplayName("BlockedException 도 ApiException 핸들러를 그대로 탄다")
    void blockedExceptionUsesApiHandler() {
        ResponseEntity<Map<String, Object>> res =
                handler.api(new BlockedException(ErrorCode.SESSION_REQUIRED, "세션이 활성화되지 않았습니다"));

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
        assertThat(res.getBody()).containsEntry("code", "SESSION_REQUIRED");
    }

    @Test
    @DisplayName("존재하지 않는 경로는 500 이 아니라 404 NOT_FOUND 로 내려간다")
    void noResourceFoundReturns404() {
        ResponseEntity<Map<String, Object>> res =
                handler.notFound(new NoResourceFoundException(HttpMethod.GET, "/nope", "/nope"));

        assertThat(res.getStatusCode().value()).isEqualTo(404);
        assertThat(res.getBody()).containsEntry("code", "NOT_FOUND");
    }

    @Test
    @DisplayName("프레임워크 예외는 원래 상태 코드를 유지하고 INVALID_REQUEST 로 표기된다")
    void frameworkExceptionKeepsStatus() {
        ResponseEntity<Map<String, Object>> res =
                handler.framework(new ErrorResponseException(HttpStatus.METHOD_NOT_ALLOWED));

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.METHOD_NOT_ALLOWED);
        assertThat(res.getBody()).containsEntry("code", "INVALID_REQUEST");
    }

    @Test
    @DisplayName("쿼리 파라미터 타입 불일치(?page=abc)는 500 이 아니라 400 INVALID_REQUEST 다")
    void typeMismatchIs400() {
        ResponseEntity<Map<String, Object>> res =
                handler.badRequest(new TypeMismatchException("abc", int.class));

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(res.getBody()).containsEntry("code", "INVALID_REQUEST");
    }

    @Test
    @DisplayName("필수 파라미터 누락은 400 이고 detail 에 파라미터 이름이 실린다")
    void missingParameterIs400WithDetail() {
        ResponseEntity<Map<String, Object>> res =
                handler.badRequest(new MissingServletRequestParameterException("period", "String"));

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(res.getBody()).containsEntry("code", "INVALID_REQUEST").containsEntry("detail", "period");
    }

    @Test
    @DisplayName("본문 역직렬화 실패도 400 INVALID_REQUEST 다")
    void messageConversionIs400() {
        ResponseEntity<Map<String, Object>> res =
                handler.badRequest(new HttpMessageConversionException("bad body"));

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
        assertThat(res.getBody()).containsEntry("code", "INVALID_REQUEST");
    }

    @Test
    @DisplayName("ErrorResponse 를 구현한 스프링 예외(405 등)는 catch-all 에서도 원 상태를 유지한다")
    void errorResponseKeepsStatusInCatchAll() {
        ResponseEntity<Map<String, Object>> res =
                handler.internal(new HttpRequestMethodNotSupportedException("PATCH"));

        assertThat(res.getStatusCode()).isEqualTo(HttpStatus.METHOD_NOT_ALLOWED);
        assertThat(res.getBody()).containsEntry("code", "INVALID_REQUEST");
    }

    @Test
    @DisplayName("나머지 모든 예외는 500 INTERNAL_ERROR 로 감싼다")
    void unknownExceptionReturns500() {
        ResponseEntity<Map<String, Object>> res = handler.internal(new IllegalStateException("boom"));

        assertThat(res.getStatusCode().value()).isEqualTo(500);
        assertThat(res.getBody()).containsEntry("code", "INTERNAL_ERROR");
    }
}
