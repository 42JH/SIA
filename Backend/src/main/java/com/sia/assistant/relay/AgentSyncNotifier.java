package com.sia.assistant.relay;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.NullNode;
import com.sia.assistant.profile.CalibProfileService;
import com.sia.assistant.profile.VoiceProfileService;
import com.sia.assistant.settings.BlobService;
import com.sia.assistant.settings.GestureService;
import com.sia.assistant.settings.SettingsService;
import com.sia.assistant.ws.AgentHub;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.stereotype.Component;

/**
 * AI 에 내려가는 동기화 페이로드의 유일한 조립 지점 (PROTOCOL.md §0.1).
 * blobs = {gestures: [{id, name, sha256}], wakeword: sha256|null,
 *          voice: {id, sha256}|null, calib: {id, sha256, screenW, screenH}|null}
 * — 커스텀 제스처 템플릿은 제스처별 참조 목록(2026-09-02, 흐름도 03), 프로필은 "활성 프로필 하나"만 본다.
 * settings_changed / recognition_start / hello_ack 가 전부 이 형식을 쓴다.
 */
@Component
public class AgentSyncNotifier {

    private static final Logger log = LoggerFactory.getLogger(AgentSyncNotifier.class);

    private final AgentHub agentHub;
    private final ObjectMapper om;
    // 설정·blob·프로필·제스처 서비스들이 저장 후 이 클래스를 부른다 — 순환은 지연 조회로 끊는다.
    private final ObjectProvider<SettingsService> settingsService;
    private final ObjectProvider<BlobService> blobService;
    private final ObjectProvider<VoiceProfileService> voiceProfileService;
    private final ObjectProvider<CalibProfileService> calibProfileService;
    private final ObjectProvider<GestureService> gestureService;

    public AgentSyncNotifier(AgentHub agentHub, ObjectMapper om,
                             ObjectProvider<SettingsService> settingsService,
                             ObjectProvider<BlobService> blobService,
                             ObjectProvider<VoiceProfileService> voiceProfileService,
                             ObjectProvider<CalibProfileService> calibProfileService,
                             ObjectProvider<GestureService> gestureService) {
        this.agentHub = agentHub;
        this.om = om;
        this.settingsService = settingsService;
        this.blobService = blobService;
        this.voiceProfileService = voiceProfileService;
        this.calibProfileService = calibProfileService;
        this.gestureService = gestureService;
    }

    /** hello_ack 용 — {settingsVersion, blobs}. */
    public Map<String, Object> helloAckBody() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("settingsVersion", settingsService.getObject().version());
        body.put("blobs", blobs());
        return body;
    }

    /** recognition_start / settings_changed 용 — {settingsVersion, settings, blobs, disabledGestures}. */
    public Map<String, Object> syncBody() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("settingsVersion", settingsService.getObject().version());
        body.put("settings", parseSettings());
        body.put("blobs", blobs());
        body.put("disabledGestures", disabledGestures());
        return body;
    }

    /** 설정·blob·프로필·제스처 토글이 바뀔 때의 공용 통지. */
    public void notifySettingsChanged() {
        agentHub.send("settings_changed", syncBody());
    }

    /**
     * blobs 맵 — gestures 는 템플릿을 가진 커스텀 제스처 전부의 {id, name, sha256} 목록(없으면 빈 배열),
     * wakeword 는 sha256|null, voice·calib 은 활성 프로필 참조|null.
     */
    public Map<String, Object> blobs() {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("gestures", gestureService.getObject().customNpzRefs());
        out.put("wakeword", blobService.getObject().hashes().get("wakeword"));
        out.put("voice", voiceProfileService.getObject().activeRefOrNull());
        out.put("calib", calibProfileService.getObject().activeRefOrNull());
        return out;
    }

    private List<String> disabledGestures() {
        return gestureService.getObject().disabledNames();
    }

    private JsonNode parseSettings() {
        try {
            return om.readTree(settingsService.getObject().rawJson());
        } catch (Exception e) {
            log.error("settings_json 파싱 실패 — null 로 보냅니다", e);
            return NullNode.getInstance();
        }
    }
}
