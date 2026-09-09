package com.sia.assistant.config;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Boot 4 는 Jackson 3(tools.jackson)를 기본 ObjectMapper 빈으로 등록한다.
 * 내부 코드(WS 봉투 직렬화, runtime.json, JsonNode 라우팅)는 Jackson 2(com.fasterxml)를 쓰므로
 * 그 ObjectMapper 를 직접 빈으로 올린다. REST 응답 직렬화는 Boot 의 Jackson 3 컨버터가 그대로 담당한다
 * (@JsonInclude 등 애노테이션 패키지는 잭슨 2·3 이 공유한다).
 */
@Configuration
public class JacksonConfig {

    @Bean
    public ObjectMapper fasterxmlObjectMapper() {
        return new ObjectMapper();
    }
}
