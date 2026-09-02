package com.sia.assistant.ws;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Component;

/** /ws/agent — AI 프로세스와의 이벤트 채널. */
@Component
public class AgentHub extends BaseHub {

    private final ApplicationEventPublisher events;

    public AgentHub(ObjectMapper om, ApplicationEventPublisher events) {
        super(om);
        this.events = events;
    }

    @Override
    protected String name() {
        return "ws/agent";
    }

    @Override
    protected void onMessage(String type, JsonNode data) {
        events.publishEvent(new WsEvents.AgentMessage(type, data));
    }

    @Override
    protected void onConnected() {
        events.publishEvent(new WsEvents.AgentConnected());
    }

    @Override
    protected void onDisconnected() {
        events.publishEvent(new WsEvents.AgentDisconnected());
    }
}
