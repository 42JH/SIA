package com.sia.assistant.bootstrap;

import com.sia.assistant.model.ModelManager;
import com.sia.assistant.relay.AgentSyncNotifier;
import com.sia.assistant.settings.SettingsService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import com.sia.assistant.ws.WsEvents;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

/**
 * AI 부팅 시퀀스의 지휘자 (다이어그램 03).
 * hello → hello_ack + 설정 ack → 모델 적재 → (전부 로드 또는 0개) → recognition_start
 * → recognition_started → FE 에 PASSIVE 초기 통지. 연결이 끊기면 다음 hello 에서 처음부터.
 * 페이로드(blobs — 활성 프로필 참조 포함, disabledGestures)는 AgentSyncNotifier 가 조립한다.
 */
@Component
public class AgentBootstrapper {

    private static final Logger log = LoggerFactory.getLogger(AgentBootstrapper.class);

    private final AgentHub agentHub;
    private final FeHub feHub;
    private final SettingsService settingsService;
    private final AgentSyncNotifier notifier;
    private final ModelManager modelManager;

    private final AtomicBoolean recognitionStartSent = new AtomicBoolean(false);

    public AgentBootstrapper(AgentHub agentHub, FeHub feHub, SettingsService settingsService,
                             AgentSyncNotifier notifier, ModelManager modelManager) {
        this.agentHub = agentHub;
        this.feHub = feHub;
        this.settingsService = settingsService;
        this.notifier = notifier;
        this.modelManager = modelManager;
    }

    public void onHello(JsonNode data) {
        recognitionStartSent.set(false);
        int version = settingsService.version();
        agentHub.send("hello_ack", notifier.helloAckBody());
        settingsService.ack(version, data.path("agentVersion").asText(null));
        modelManager.beginLoading(this::sendRecognitionStart);
    }

    private void sendRecognitionStart() {
        if (!recognitionStartSent.compareAndSet(false, true)) {
            return;
        }
        agentHub.send("recognition_start", notifier.syncBody());
    }

    public void onRecognitionStarted() {
        feHub.send("session_state", Map.of("state", "PASSIVE"));
    }

    @EventListener
    public void onAgentDisconnected(WsEvents.AgentDisconnected e) {
        recognitionStartSent.set(false);
        modelManager.reset();
        log.info("AI 연결 종료 — 다음 hello 에서 부트스트랩을 다시 시작합니다");
    }
}
