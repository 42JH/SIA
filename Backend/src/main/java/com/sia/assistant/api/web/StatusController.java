package com.sia.assistant.api.web;

import com.sia.assistant.profile.CalibProfileService;
import com.sia.assistant.profile.VoiceProfileService;
import com.sia.assistant.session.SessionService;
import com.sia.assistant.settings.SettingsService;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.ExtHub;
import com.sia.assistant.ws.FeHub;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/** 한 화면 요약 상태 (GET /api/status) — FE 대시보드 헤더가 주기 조회한다. */
@RestController
public class StatusController {

    private final AgentHub agentHub;
    private final FeHub feHub;
    private final ExtHub extHub;
    private final SettingsService settingsService;
    private final SessionService sessionService;
    private final VoiceProfileService voiceProfiles;
    private final CalibProfileService calibProfiles;
    private final JdbcTemplate jdbc;

    public StatusController(AgentHub agentHub, FeHub feHub, ExtHub extHub, SettingsService settingsService,
                            SessionService sessionService, VoiceProfileService voiceProfiles,
                            CalibProfileService calibProfiles, JdbcTemplate jdbc) {
        this.agentHub = agentHub;
        this.feHub = feHub;
        this.extHub = extHub;
        this.settingsService = settingsService;
        this.sessionService = sessionService;
        this.voiceProfiles = voiceProfiles;
        this.calibProfiles = calibProfiles;
        this.jdbc = jdbc;
    }

    @GetMapping("/api/status")
    public Map<String, Object> status() {
        Map<String, Object> settings = settingsService.get();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("agentConnected", agentHub.connected());
        body.put("feConnected", feHub.connected());
        body.put("extConnected", extHub.connected());
        body.put("settingsVersion", settings.get("version"));
        body.put("agentSyncedVersion", settings.get("agentSyncedVersion"));
        body.put("agentVersion", settings.get("agentVersion"));
        body.put("settingsPending", settings.get("settingsPending"));

        SessionService.Active active = sessionService.activeOrNull();
        if (active == null) {
            body.put("activeSession", null);
        } else {
            Map<String, Object> session = new LinkedHashMap<>();
            session.put("id", active.id());
            session.put("remainingSec", sessionService.remainingSec());
            body.put("activeSession", session);
        }
        body.put("activeVoiceId", voiceProfiles.activeIdOrNull());
        body.put("activeCalibId", calibProfiles.activeIdOrNull());
        body.put("mcpToolCount",
                jdbc.queryForObject("SELECT COUNT(*) FROM tool WHERE available = 1", Integer.class));
        return body;
    }
}
