package com.sia.assistant.api.agent;

import com.sia.assistant.registration.RegistrationOrchestrator;
import com.sia.assistant.settings.GestureService;
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
 * AI 전용 커스텀 제스처 템플릿 채널 — 제스처별 npz 1개 (흐름도 03 "gesture.npz").
 *  - 등록 진행 중: PUT /api/agent/gestures/{tempId}/npz — reg_captured 를 보내기 전에 올린다.
 *    확정 전이라 RegistrationOrchestrator 메모리에 있고, macro_assign 이 gesture 행으로 확정한다.
 *  - 상시: GET /api/agent/gestures/{id}/npz (ETag=sha256, If-None-Match 일치 시 304) —
 *    gesture_registered {id, sha256} 를 받은 뒤, 그리고 hello_ack·recognition_start 의 blobs.gestures 와
 *    로컬 캐시를 대조해 sha256 이 다른 것만 내려받는다.
 * 보이스·보정 npz 는 AgentProfileController, 호출어 모델은 AgentBlobController 다.
 */
@RestController
@RequestMapping("/api/agent/gestures")
public class AgentGestureController {

    private final RegistrationOrchestrator registration;
    private final GestureService gestureService;

    public AgentGestureController(RegistrationOrchestrator registration, GestureService gestureService) {
        this.registration = registration;
        this.gestureService = gestureService;
    }

    /** 등록 중 템플릿 업로드 — 1B ~ 5MB. tempId 가 진행 중 등록과 다르면 404 GESTURE_NOT_FOUND. */
    @PutMapping(value = "/{tempId}/npz", consumes = MediaType.APPLICATION_OCTET_STREAM_VALUE)
    public ResponseEntity<Void> putNpz(@PathVariable String tempId, @RequestBody byte[] payload) {
        registration.attachNpz(tempId, payload);
        return ResponseEntity.noContent().build();
    }

    /** 확정된 제스처의 템플릿 — 행이 없으면 404 GESTURE_NOT_FOUND, 기본 제공(템플릿 없음)이면 404 BLOB_NOT_FOUND. */
    @GetMapping("/{id:\\d+}/npz")
    public ResponseEntity<byte[]> getNpz(@PathVariable long id,
                                         @RequestHeader(value = "If-None-Match", required = false) String ifNoneMatch) {
        GestureService.NpzMeta meta = gestureService.npzMeta(id);
        String etag = "\"" + meta.sha256() + "\"";
        if (ifNoneMatch != null && AgentBlobController.stripEtag(ifNoneMatch).equalsIgnoreCase(meta.sha256())) {
            return ResponseEntity.status(HttpStatus.NOT_MODIFIED).eTag(etag).build();
        }
        return ResponseEntity.ok()
                .eTag(etag)
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .body(gestureService.npz(id));
    }
}
