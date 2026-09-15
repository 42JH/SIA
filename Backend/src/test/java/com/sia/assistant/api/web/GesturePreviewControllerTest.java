package com.sia.assistant.api.web;

import static org.mockito.Mockito.mock;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.sia.assistant.common.GlobalExceptionHandler;
import com.sia.assistant.config.DataDirs;
import com.sia.assistant.relay.AgentSyncNotifier;
import com.sia.assistant.settings.GestureService;
import com.sia.assistant.ws.AgentHub;
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
 * GET /api/gestures/{id}/video 가 실제로 내보내는 응답 — 기본 제공 제스처는 배포에 실린 예시 그림이
 * 나가고 Content-Type 은 그 파일의 확장자가 정한다. 서비스 단위 테스트는 파일명까지만 보므로
 * 클래스패스 리소스가 본문으로 제대로 나가는 층은 여기서만 지켜진다.
 *
 * <p>애셋은 테스트 리소스의 Open_Palm.jpg 다 (DefaultGestureImagesTest 참고).
 */
class GesturePreviewControllerTest {

    private MockMvc mvc;
    private long builtinId;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp(@TempDir Path dir) throws Exception {
        DriverManagerDataSource ds = new DriverManagerDataSource("jdbc:sqlite:" + dir.resolve("preview-test.db"));
        Flyway.configure().dataSource(ds).locations("classpath:db/migration").load().migrate();
        JdbcTemplate jdbc = new JdbcTemplate(ds);
        jdbc.update("INSERT INTO gesture (custom, kind, context, name, label, repeatable, hands, motion)"
                + " VALUES (0, 'HAND', NULL, 'Open_Palm', '손바닥 펴기', 0, 1, 'STATIC')");
        builtinId = jdbc.queryForObject("SELECT id FROM gesture WHERE name = 'Open_Palm'", Long.class);
        ObjectProvider<AgentSyncNotifier> notifierProvider = mock(ObjectProvider.class);
        GestureService service = new GestureService(jdbc, new ObjectMapper(), mock(AgentHub.class),
                new DataDirs(dir.toString()), notifierProvider);
        mvc = MockMvcBuilders.standaloneSetup(new GestureMappingController(service, new ObjectMapper()))
                .setControllerAdvice(new GlobalExceptionHandler())  // 없는 id 의 404 는 여기서 나온다
                .build();
    }

    @Test
    @DisplayName("기본 제공 제스처는 배포에 실린 예시 그림이 image/jpeg 로 나간다")
    void builtinServesSeedImage() throws Exception {
        mvc.perform(get("/api/gestures/" + builtinId + "/video"))
                .andExpect(status().isOk())
                .andExpect(content().contentType(MediaType.IMAGE_JPEG))
                .andExpect(content().bytes(new byte[] {(byte) 0xff, (byte) 0xd8, (byte) 0xff, (byte) 0xd9}));
    }

    @Test
    @DisplayName("없는 제스처는 404 — 미리보기 없음과 제스처 없음은 둘 다 404 지만 본문이 다르다")
    void unknownGestureIs404() throws Exception {
        mvc.perform(get("/api/gestures/9999/video")).andExpect(status().isNotFound());
    }
}
