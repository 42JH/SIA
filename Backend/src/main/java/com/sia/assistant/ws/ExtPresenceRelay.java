package com.sia.assistant.ws;

import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

/** 브라우저 확장 WS 연결 상태를 FE 에 중계한다 ("페이지 요약 가능" 배지용). */
@Component
public class ExtPresenceRelay {

    private final FeHub feHub;

    public ExtPresenceRelay(FeHub feHub) {
        this.feHub = feHub;
    }

    @EventListener
    public void onConnected(WsEvents.ExtConnected e) {
        feHub.send("ext_status", java.util.Map.of("connected", true));
    }

    @EventListener
    public void onDisconnected(WsEvents.ExtDisconnected e) {
        feHub.send("ext_status", java.util.Map.of("connected", false));
    }
}
