package com.sia.assistant.ws;

import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;

/** AI WS 연결 상태를 FE 에 중계한다. */
@Component
public class AgentPresenceRelay {

    private final FeHub feHub;

    public AgentPresenceRelay(FeHub feHub) {
        this.feHub = feHub;
    }

    @EventListener
    public void onConnected(WsEvents.AgentConnected e) {
        feHub.send("agent_status", java.util.Map.of("connected", true));
    }

    @EventListener
    public void onDisconnected(WsEvents.AgentDisconnected e) {
        feHub.send("agent_status", java.util.Map.of("connected", false));
    }
}
