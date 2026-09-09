package com.sia.assistant.model;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.timeout;
import static org.mockito.Mockito.verify;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.config.DataDirs;
import com.sia.assistant.ws.AgentHub;
import com.sia.assistant.ws.FeHub;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import tools.jackson.databind.ObjectMapper;

/**
 * 모델 상태 조회와 재다운로드 요청 (GET /api/models · POST /api/models/{name}/redownload).
 * 실제 네트워크는 쓰지 않는다 — 닫힌 포트로 향하는 URL 로 실패 경로(model_error)만 확인한다.
 */
class ModelManagerTest {

    private Path root;
    private FeHub feHub;
    private ModelManager manager;

    @BeforeEach
    void setUp(@TempDir Path dir) throws Exception {
        root = dir;
        Files.createDirectories(root.resolve("models"));
        Files.createDirectories(root.resolve("tmp"));
        Files.writeString(root.resolve("models.json"), """
                {"models":[{"name":"tiny","url":"http://127.0.0.1:1/tiny.bin","sha256":"00","filename":"tiny.bin"}]}
                """);
        feHub = mock(FeHub.class);
        manager = new ModelManager(mock(AgentHub.class), feHub, new DataDirs(root.toString()), new ObjectMapper());
    }

    @Test
    @DisplayName("GET /api/models 는 models.json 의 모델마다 상태 한 줄을 준다")
    void statusListsEveryModel() {
        List<Map<String, Object>> status = manager.status();

        assertThat(status).singleElement().satisfies(m -> assertThat(m)
                .containsEntry("name", "tiny")
                .containsEntry("filename", "tiny.bin")
                .containsEntry("fileReady", false)
                .containsEntry("loaded", false)
                .containsEntry("downloading", false));
    }

    @Test
    @DisplayName("모르는 모델 이름의 재다운로드 요청은 NOT_FOUND 다")
    void redownloadUnknownModelIsNotFound() {
        assertThatThrownBy(() -> manager.redownload("nope"))
                .isInstanceOfSatisfying(ApiException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.NOT_FOUND));
    }

    @Test
    @DisplayName("재다운로드는 비동기로 돌고, 받지 못하면 FE 에 model_error 가 간다")
    void redownloadFailureReportsModelError() {
        manager.redownload("tiny");

        verify(feHub, timeout(15_000)).send(eq("model_error"), any());
        assertThat(manager.status().get(0)).containsEntry("fileReady", false);
    }
}
