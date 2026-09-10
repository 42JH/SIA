package com.sia.assistant.registration;

import com.sia.assistant.config.DataDirs;
import java.nio.file.Files;
import java.nio.file.Path;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/**
 * 등록 미리보기 webm 정적 서빙.
 * ★ 사용자 카메라 영상 — 루프백 FE 전용이며 PC 밖으로 반출하지 않는다.
 */
@RestController
public class PreviewController {

    private final DataDirs dataDirs;

    public PreviewController(DataDirs dataDirs) {
        this.dataDirs = dataDirs;
    }

    @GetMapping("/api/previews/{file:[a-zA-Z0-9-]+\\.webm}")
    public ResponseEntity<Resource> preview(@PathVariable("file") String file) {
        Path base = dataDirs.previews().toAbsolutePath().normalize();
        Path target = base.resolve(file).normalize();
        // 패턴이 이미 경로 문자를 막지만, 탈출은 이중으로 차단한다.
        if (!target.startsWith(base) || !Files.isRegularFile(target)) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType("video/webm"))
                .body(new FileSystemResource(target));
    }
}
