package com.sia.assistant.config;

import jakarta.annotation.PostConstruct;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

/**
 * 런타임 데이터 디렉터리의 유일한 결정자.
 * 기본: %APPDATA%/SIA (APPDATA 없으면 ~/.sia). SIA_DATA_DIR 로 대체 가능.
 *  - previews/  등록 미리보기 webm (★ 사용자 카메라 영상 — PC 밖 반출 금지)
 *  - gestures/  제스처별 등록 영상 webm — 목록·상세에서 다시 보여 주는 영구 보관본 (반출 금지 동일)
 *  - models/    다운로드·검증이 끝난 모델 파일
 *  - tmp/       다운로드 임시 파일, 프레임 버퍼 등
 */
@Component
public class DataDirs {

    private final Path root;

    public DataDirs(@Value("${sia.data-dir:}") String configured) {
        if (configured != null && !configured.isBlank()) {
            this.root = Path.of(configured);
        } else {
            String appData = System.getenv("APPDATA");
            this.root = appData != null
                    ? Path.of(appData, "SIA")
                    : Path.of(System.getProperty("user.home"), ".sia");
        }
    }

    @PostConstruct
    void ensure() throws IOException {
        Files.createDirectories(previews());
        Files.createDirectories(gestures());
        Files.createDirectories(models());
        Files.createDirectories(tmp());
    }

    public Path root() {
        return root;
    }

    public Path previews() {
        return root.resolve("previews");
    }

    public Path gestures() {
        return root.resolve("gestures");
    }

    public Path models() {
        return root.resolve("models");
    }

    public Path tmp() {
        return root.resolve("tmp");
    }
}
