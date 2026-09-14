package com.sia.assistant.api.agent;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.settings.BlobService;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * AI 전용 전역 npz 업/다운로드 (PROTOCOL.md §3) — 이름은 wakeword 1종.
 * (시선 보정·보이스 npz 는 AgentProfileController, 커스텀 제스처 템플릿은 제스처별로 AgentGestureController.)
 * GET: ETag=sha256, If-None-Match 일치 시 304. PUT: octet-stream, 동일 sha256 이면 저장 생략 — 어느 쪽이든 204.
 */
@RestController
@RequestMapping("/api/agent/blobs")
public class AgentBlobController {

    private final BlobService blobService;

    public AgentBlobController(BlobService blobService) {
        this.blobService = blobService;
    }

    @GetMapping("/{name}")
    public ResponseEntity<byte[]> get(@PathVariable String name,
                                      @RequestHeader(value = "If-None-Match", required = false) String ifNoneMatch) {
        BlobService.Meta meta = blobService.meta(name)
                .orElseThrow(() -> new ApiException(ErrorCode.BLOB_NOT_FOUND, "저장된 데이터가 없습니다: " + name));
        String etag = "\"" + meta.sha256() + "\"";
        if (ifNoneMatch != null && stripEtag(ifNoneMatch).equalsIgnoreCase(meta.sha256())) {
            return ResponseEntity.status(HttpStatus.NOT_MODIFIED).eTag(etag).build();
        }
        return ResponseEntity.ok()
                .eTag(etag)
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .body(blobService.payload(name));
    }

    @PutMapping(value = "/{name}", consumes = MediaType.APPLICATION_OCTET_STREAM_VALUE)
    public ResponseEntity<Void> put(@PathVariable String name, @RequestBody byte[] payload) {
        blobService.put(name, payload);
        return ResponseEntity.noContent().build();
    }

    /** If-None-Match 는 `"abc"` / `W/"abc"` / `abc` 어느 형태로 와도 sha256 만 남긴다. */
    static String stripEtag(String header) {
        String v = header.trim();
        if (v.startsWith("W/")) {
            v = v.substring(2).trim();
        }
        if (v.length() >= 2 && v.startsWith("\"") && v.endsWith("\"")) {
            v = v.substring(1, v.length() - 1);
        }
        return v;
    }
}
