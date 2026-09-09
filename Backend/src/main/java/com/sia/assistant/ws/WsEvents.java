package com.sia.assistant.ws;

import tools.jackson.databind.JsonNode;

/**
 * WS 수신을 스프링 ApplicationEvent 로 옮긴 것.
 * 기능 모듈은 @EventListener 로 구독하고, 송신은 AgentHub / FeHub 를 주입받아 send() 한다.
 * (허브 → 이벤트 → 리스너 → 허브 방향이라 순환 의존이 생기지 않는다)
 */
public final class WsEvents {

    private WsEvents() {
    }

    /** /ws/agent 수신 메시지 */
    public record AgentMessage(String type, JsonNode data) {
    }

    /** /ws/fe 수신 메시지 */
    public record FeMessage(String type, JsonNode data) {
    }

    /** /ws/ext 수신 메시지 (브라우저 확장) */
    public record ExtMessage(String type, JsonNode data) {
    }

    public record AgentConnected() {
    }

    public record AgentDisconnected() {
    }

    public record FeConnected() {
    }

    public record ExtConnected() {
    }

    public record ExtDisconnected() {
    }
}
