package com.sia.assistant.api.web;

import static org.mockito.Mockito.mock;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.sia.assistant.relay.AgentSyncNotifier;
import com.sia.assistant.settings.SettingsService;
import com.sia.assistant.ws.FeHub;
import java.nio.file.Path;
import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import tools.jackson.databind.ObjectMapper;

/**
 * 설정 응답이 <b>실제로 나가는 JSON</b> 을 검증한다 — 반환 Map 만 단언하면 놓치는 층이 있다.
 *
 * <p>이 테스트가 생긴 이유: 예전에는 응답 직렬화(Jackson 3)와 우리 코드(Jackson 2)의 라이브러리가
 * 갈려서, 응답에 담은 {@code JsonNode} 가 컨버터에게 모르는 POJO 로 보여 게터를 나열한
 * {@code {"array":false,"nodeType":"OBJECT",…}} 가 나갔다. 값은 정상이고 직렬화만 깨지므로
 * 서비스·컨트롤러 단위 테스트로는 잡히지 않았다. Jackson 3 통일(S15P21D106-197)로 원인은 사라졌지만,
 * 응답 JSON 을 보는 층이 없으면 같은 종류가 다시 들어와도 조용하다 — 그 층을 지키는 것이 이 테스트다.
 *
 * <p>standalone 설정이라 컨텍스트를 띄우지 않지만 기본 메시지 컨버터는 실제 것과 같다.
 */
class SettingsControllerJsonTest {

    private final ObjectMapper om = new ObjectMapper();
    private MockMvc mvc;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp(@TempDir Path dir) {
        // 진짜 SQLite + 진짜 마이그레이션 — V1 이 넣는 설정 시드를 그대로 읽는다
        DriverManagerDataSource ds = new DriverManagerDataSource(
                "jdbc:sqlite:" + dir.resolve("settings-json-test.db"));
        Flyway.configure().dataSource(ds).locations("classpath:db/migration").load().migrate();
        ObjectProvider<AgentSyncNotifier> notifierProvider = mock(ObjectProvider.class);
        SettingsService service = new SettingsService(
                new JdbcTemplate(ds), om, mock(FeHub.class), notifierProvider);
        mvc = MockMvcBuilders.standaloneSetup(new SettingsController(service, om)).build();
    }

    @Test
    @DisplayName("GET 응답의 settings 는 설정 문서 그 자체다 — Jackson 내부 상태가 새지 않는다")
    void getReturnsTheSettingsDocument() throws Exception {
        mvc.perform(get("/api/settings"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.settings.wakeWord").value("시아"))
                .andExpect(jsonPath("$.settings.sessionSeconds").value(15))
                .andExpect(jsonPath("$.settings.autoStart").value(true))
                .andExpect(jsonPath("$.settings.gazeCursor").value(false))
                // JsonNode 를 POJO 로 직렬화하면 나타나는 키들 — 하나라도 있으면 그 회귀다
                .andExpect(jsonPath("$.settings.nodeType").doesNotExist())
                .andExpect(jsonPath("$.settings.containerNode").doesNotExist())
                .andExpect(jsonPath("$.settings.bigDecimal").doesNotExist());
    }

    @Test
    @DisplayName("PUT 의 200 응답도 같은 형식이다 — FE 는 이 응답으로 저장 결과를 확인한다")
    void putReturnsTheSavedDocument() throws Exception {
        String body = """
                {"settings": {"wakeWord": "시아", "sessionSeconds": 15, "autoStart": true,
                 "gazeCursor": false, "micDevice": "USB Mic", "cameraDevice": "HD Webcam",
                 "micDeviceId": "{0.0.1.00000000}.{a53af75a}", "cameraDeviceId": "path",
                 "previewMirror": true}}""";

        mvc.perform(put("/api/settings").contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.version").value(2))
                .andExpect(jsonPath("$.settings.micDevice").value("USB Mic"))
                .andExpect(jsonPath("$.settings.micDeviceId").value("{0.0.1.00000000}.{a53af75a}"))
                .andExpect(jsonPath("$.settings.cameraDeviceId").value("path"))
                // 미지의 키도 그대로 돌아온다 (settings 는 자유 JSON 이다)
                .andExpect(jsonPath("$.settings.previewMirror").value(true))
                .andExpect(jsonPath("$.settings.nodeType").doesNotExist());
    }
}
