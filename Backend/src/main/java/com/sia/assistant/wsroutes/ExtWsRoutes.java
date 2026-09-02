package com.sia.assistant.wsroutes;

import com.sia.assistant.domtext.DomTextService;
import com.sia.assistant.ws.ExtHub;
import com.sia.assistant.ws.WsEvents;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

/** /ws/ext 수신 라우트 — 브라우저 확장이 보내는 메시지 전량 (PROTOCOL.md §2.5). */
@Component
public class ExtWsRoutes {

    private static final Logger log = LoggerFactory.getLogger(ExtWsRoutes.class);

    private final ExtHub extHub;
    private final DomTextService domTextService;

    public ExtWsRoutes(ExtHub extHub, DomTextService domTextService) {
        this.extHub = extHub;
        this.domTextService = domTextService;
    }

    @EventListener
    public void on(WsEvents.ExtMessage msg) {
        switch (msg.type()) {
            case "hello" -> log.info("[ws/ext] 확장 접속 — 버전 {}", msg.data().path("extVersion").asText("?"));
            case "dom_text" -> domTextService.onReply(msg.data());
            // MV3 서비스 워커 생존 유지용 하트비트 — 내용 없음
            case "ping" -> extHub.send("pong", Map.of());
            default -> log.debug("[ws/ext] 모르는 type 무시: {}", msg.type());
        }
    }
}
