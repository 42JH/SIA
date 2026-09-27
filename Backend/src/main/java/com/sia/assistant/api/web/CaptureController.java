package com.sia.assistant.api.web;

import com.sia.assistant.control.screen.CaptureService;
import java.nio.file.Path;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/**
 * 캡처 결과물 서빙 — GET /api/captures/{file}. FE 가 capture_saved 의 url 로 썸네일·미리보기를 그린다.
 * 파일명 패턴만 매칭하고 디렉터리 이탈은 CaptureService.resolve 가 다시 검사한다. 사용자 화면 이미지라 루프백 FE 전용이다.
 */
@RestController
public class CaptureController {

    private final CaptureService captureService;

    public CaptureController(CaptureService captureService) {
        this.captureService = captureService;
    }

    @GetMapping("/api/captures/{file:[A-Za-z0-9_-]+\\.png}")
    public ResponseEntity<Resource> get(@PathVariable String file) {
        Path target = captureService.resolve(file);
        if (target == null) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok()
                .contentType(MediaType.IMAGE_PNG)
                .body(new FileSystemResource(target));
    }
}
