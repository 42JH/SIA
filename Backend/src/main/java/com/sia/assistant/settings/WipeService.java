package com.sia.assistant.settings;

import com.sia.assistant.profile.CalibProfileService;
import com.sia.assistant.profile.VoiceProfileService;
import com.sia.assistant.session.SessionService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

/**
 * 전체 삭제(DELETE /api/data).
 * FK 역순으로 지우고, 기본 제스처 매핑 11건(DefaultMappings)을 되살린 뒤, 설정을 시드로 되돌린다.
 * 에이전트에는 wipe(로컬 캐시 삭제), FE 에는 settings_sync 를 통지한다.
 */
@Service
public class WipeService {

    private static final Logger log = LoggerFactory.getLogger(WipeService.class);

    private final JdbcTemplate jdbc;
    private final TransactionTemplate tx;
    private final SettingsService settingsService;
    private final SessionService sessionService;
    private final GestureService gestureService;
    private final VoiceProfileService voiceProfileService;
    private final CalibProfileService calibProfileService;
    private final AgentHub agentHub;
    private final FeHub feHub;

    public WipeService(JdbcTemplate jdbc, PlatformTransactionManager txManager,
                       SettingsService settingsService, SessionService sessionService,
                       GestureService gestureService, VoiceProfileService voiceProfileService,
                       CalibProfileService calibProfileService, AgentHub agentHub, FeHub feHub) {
        this.jdbc = jdbc;
        this.tx = new TransactionTemplate(txManager);
        this.settingsService = settingsService;
        this.sessionService = sessionService;
        this.gestureService = gestureService;
        this.voiceProfileService = voiceProfileService;
        this.calibProfileService = calibProfileService;
        this.agentHub = agentHub;
        this.feHub = feHub;
    }

    public void wipeAll() {
        tx.executeWithoutResult(status -> {
            // FK 역순 — 자식 먼저
            jdbc.update("DELETE FROM usage_event");
            jdbc.update("DELETE FROM tool_call");
            jdbc.update("DELETE FROM gesture_step");
            jdbc.update("DELETE FROM gesture");
            jdbc.update("DELETE FROM session");
            jdbc.update("DELETE FROM app_target");
            jdbc.update("DELETE FROM blob");
            voiceProfileService.deleteAll();
            calibProfileService.deleteAll();
            int seeded = DefaultMappings.seedInto(jdbc);
            log.info("전체 삭제 완료 — 기본 매핑 {}건과 시드 설정으로 복원했습니다", seeded);
        });
        gestureService.deleteAllVideos(); // 등록 영상 파일 — 트랜잭션 밖(파일 시스템)
        settingsService.resetToSeed();
        sessionService.reset();

        agentHub.send("wipe", Map.of());
        Map<String, Object> settings = settingsService.get();
        Map<String, Object> sync = new LinkedHashMap<>();
        sync.put("settingsVersion", settings.get("version"));
        sync.put("agentSyncedVersion", settings.get("agentSyncedVersion"));
        feHub.send("settings_sync", sync);
    }
}
