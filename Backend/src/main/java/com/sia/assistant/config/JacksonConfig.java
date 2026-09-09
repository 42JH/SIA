package com.sia.assistant.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Boot 4 는 Jackson 3(tools.jackson)를 기본 ObjectMapper 빈으로 등록한다.
 * 내부 코드(WS 봉투 직렬화, runtime.json, JsonNode 라우팅)는 Jackson 2(com.fasterxml)를 쓰므로
 * 그 ObjectMapper 를 직접 빈으로 올린다. REST 응답 직렬화는 Boot 의 Jackson 3 컨버터가 그대로 담당한다
 * (@JsonInclude 등 애노테이션 패키지는 잭슨 2·3 이 공유한다).
 *
 * <p>★ 그래서 <b>응답 본문에 Jackson2 {@code JsonNode} 를 담으면 안 된다</b> — Jackson 3 컨버터는
 * 그것을 모르는 POJO 로 보고 게터를 직렬화해 {@code {"array":false,"nodeType":"OBJECT",…}} 를
 * 내보낸다. DB 의 JSON 텍스트를 응답에 실을 때는 {@code readValue}/{@code convertValue} 로
 * {@code Map}·{@code List} 로 바꿔 담는다 (SettingsService.asMap · GestureService 의 args 참고).
 * 값은 정상이고 직렬화만 깨지므로 반환값 단언으로는 잡히지 않는다 — 응답 JSON 을 보는 테스트가 필요하다.
 */
@Configuration
public class JacksonConfig {

    @Bean
    public ObjectMapper fasterxmlObjectMapper() {
        return new ObjectMapper();
    }
}
