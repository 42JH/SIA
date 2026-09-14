package com.sia.assistant.config;

import io.swagger.v3.oas.models.OpenAPI;
import io.swagger.v3.oas.models.info.Info;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class OpenApiConfig {

    @Bean
    public OpenAPI openApi() {
        return new OpenAPI().info(new Info()
                .title("SIA Backend")
                .description("REST 표면 문서. WS 이벤트 계약은 docs/프로토콜.md 를 볼 것")
                .version("0.1.0"));
    }
}
