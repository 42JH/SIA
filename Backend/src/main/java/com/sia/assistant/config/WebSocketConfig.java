package com.sia.assistant.config;

import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.ExtHub;
import com.sia.assistant.ws.FeHub;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;
import org.springframework.web.socket.server.standard.ServletServerContainerFactoryBean;

@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {

    private final AgentHub agentHub;
    private final FeHub feHub;
    private final ExtHub extHub;

    public WebSocketConfig(AgentHub agentHub, FeHub feHub, ExtHub extHub) {
        this.agentHub = agentHub;
        this.feHub = feHub;
        this.extHub = extHub;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        // 네이티브 클라이언트(AI 파이썬)는 Origin 헤더가 없고, FE 는 개발 서버 또는 Tauri 오리진이다.
        registry.addHandler(agentHub, "/ws/agent")
                .setAllowedOriginPatterns("http://localhost:[*]", "http://127.0.0.1:[*]");
        registry.addHandler(feHub, "/ws/fe")
                .setAllowedOriginPatterns("http://localhost:[*]", "http://127.0.0.1:[*]", "http://tauri.localhost");
        // 브라우저 확장(MV3 서비스 워커)의 Origin 은 chrome-extension://<id> 다. 루프백 바인딩이 1차 방어선.
        registry.addHandler(extHub, "/ws/ext")
                .setAllowedOriginPatterns("chrome-extension://*", "http://localhost:[*]", "http://127.0.0.1:[*]");
    }

    /** 등록 프레임(jpeg base64)이 수백 KB 까지 갈 수 있어 버퍼를 넉넉히 잡는다. */
    @Bean
    public ServletServerContainerFactoryBean wsContainer() {
        ServletServerContainerFactoryBean container = new ServletServerContainerFactoryBean();
        container.setMaxTextMessageBufferSize(4 * 1024 * 1024);
        container.setMaxBinaryMessageBufferSize(4 * 1024 * 1024);
        container.setMaxSessionIdleTimeout(0L);
        return container;
    }
}
