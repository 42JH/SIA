package com.sia.assistant.api.web;

import com.sia.assistant.settings.BlobService;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RestController;

/**
 * 전역 npz 내보내기 (GET /api/export/blobs/{name}, 이름은 wakeword) — 첨부 다운로드.
 * 전체 삭제나 기기 교체 전에 사용자가 자기 데이터를 챙길 수 있는 복구 수단이다.
 * 프로필은 GET /api/{voices|calibs}/{id}/npz, 커스텀 제스처 템플릿은 GET /api/gestures/{id}/npz 가 같은 역할이다.
 */
@RestController
public class ExportController {

    private final BlobService blobService;

    public ExportController(BlobService blobService) {
        this.blobService = blobService;
    }

    @GetMapping("/api/export/blobs/{name}")
    public ResponseEntity<byte[]> export(@PathVariable String name) {
        byte[] payload = blobService.payload(name); // 없으면 BLOB_NOT_FOUND(404)
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"" + name + ".npz\"")
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .body(payload);
    }
}
