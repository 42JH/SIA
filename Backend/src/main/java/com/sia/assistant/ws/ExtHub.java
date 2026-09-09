package com.sia.assistant.ws;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.context.ApplicationEventPublisher;
import org.springframework.stereotype.Component;

/** /ws/ext — 브라우저 확장(DOM 텍스트 공급원)과의 이벤트 채널. */
@Component
public class ExtHub extends BaseHub {

    private final ApplicationEventPublisher events;

    public ExtHub(ObjectMapper om, ApplicationEventPublisher events) {
        super(om);
        this.events = events;
    }

    @Override
    protected String name() {
        return "ws/ext";
    }

    @Override
    protected void onMessage(String type, JsonNode data) {
        events.publishEvent(new WsEvents.ExtMessage(type, data));
    }

    @Override
    protected void onConnected() {
        events.publishEvent(new WsEvents.ExtConnected());
    }

    @Override
    protected void onDisconnected() {
        events.publishEvent(new WsEvents.ExtDisconnected());
    }
}
