package com.sia.assistant.ws;

import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/** /ws/fe — FE(WebUI)와의 이벤트 채널. */
@Component
public class FeHub extends BaseHub {

    private final ApplicationEventPublisher events;

    public FeHub(ObjectMapper om, ApplicationEventPublisher events) {
        super(om);
        this.events = events;
    }

    @Override
    protected String name() {
        return "ws/fe";
    }

    @Override
    protected void onMessage(String type, JsonNode data) {
        events.publishEvent(new WsEvents.FeMessage(type, data));
    }

    @Override
    protected void onConnected() {
        events.publishEvent(new WsEvents.FeConnected());
    }

    @Override
    protected void onDisconnected() {
    }
}
