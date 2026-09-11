package com.sia.assistant.config;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.util.UrlPathHelper;

/**
 * 요청 경로를 <b>스프링이 라우팅에 쓰는 것과 같은 기준</b>(퍼센트 디코딩·세미콜론 제거)으로 본다.
 *
 * <p>{@code request.getRequestURI()} 는 디코딩 전 원문이다. {@code /%6dcp} 는 {@code /mcp} 와
 * 다른 문자열이지만 스프링은 디코딩해서 {@code /mcp} 컨트롤러로 보낸다 — 원문으로 경로를 판정하면
 * 판정과 실행이 어긋난다. 로그에 <i>찍는</i> 용도로는 원문이 맞다(뭘 보냈는지 그대로 남아야 한다).
 * <b>판정</b>에만 이걸 쓴다.
 *
 * <p>보안 판정에는 이것도 쓰지 않는다 — 그건 SecurityConfig 의 authorizeHttpRequests 몫이다.
 */
public final class RequestPaths {

    private RequestPaths() {
    }

    public static String of(HttpServletRequest request) {
        return UrlPathHelper.defaultInstance.getPathWithinApplication(request);
    }
}
