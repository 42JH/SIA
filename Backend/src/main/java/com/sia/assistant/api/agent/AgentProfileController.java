package com.sia.assistant.api.agent;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.profile.CalibProfileService;
import com.sia.assistant.profile.VoiceProfileService;
import com.sia.assistant.registration.CalibrationOrchestrator;
import com.sia.assistant.registration.VoiceRegistrationOrchestrator;
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
 * AI 전용 프로필 바이너리 채널 (PROTOCOL.md §3).
 *  - 등록 진행 중: PUT /api/agent/voices/{tempId}/npz·sample, PUT /api/agent/calibs/{tempId}/npz —
 *    확정 전이라 오케스트레이터 메모리로 들어간다 (커밋에서 프로필 행이 된다).
 *  - 상시: GET .../active/npz (ETag/304) — 활성 프로필 교체(voice_changed·calib_changed) 후 캐시 갱신.
 *  - PUT /api/agent/voices/active/sample — ★화자 인식 시 마지막 발화로 재생 샘플 갱신 (회의 확정).
 */
@RestController
@RequestMapping("/api/agent")
public class AgentProfileController {

    private final VoiceRegistrationOrchestrator voiceReg;
    private final CalibrationOrchestrator calibReg;
    private final VoiceProfileService voiceProfiles;
    private final CalibProfileService calibProfiles;

    public AgentProfileController(VoiceRegistrationOrchestrator voiceReg, CalibrationOrchestrator calibReg,
                                  VoiceProfileService voiceProfiles, CalibProfileService calibProfiles) {
        this.voiceReg = voiceReg;
        this.calibReg = calibReg;
        this.voiceProfiles = voiceProfiles;
        this.calibProfiles = calibProfiles;
    }

    // ------------------------------------------------------------------ 보이스

    @PutMapping(value = "/voices/{tempId}/npz", consumes = MediaType.APPLICATION_OCTET_STREAM_VALUE)
    public ResponseEntity<Void> putVoiceNpz(@PathVariable String tempId, @RequestBody byte[] payload) {
        voiceReg.attachNpz(tempId, payload);
        return ResponseEntity.noContent().build();
    }

    /** 등록 중 샘플 오디오 — Content-Type 이 그대로 재생 MIME 이 된다 (audio/webm | audio/wav). */
    @PutMapping(value = "/voices/{tempId}/sample")
    public ResponseEntity<Void> putVoiceSample(@PathVariable String tempId, @RequestBody byte[] payload,
                                               @RequestHeader(value = "Content-Type", required = false) String contentType) {
        if ("active".equals(tempId)) {
            // 화자 인식 직후 — 활성 프로필의 샘플을 마지막 발화로 교체한다
            voiceProfiles.updateActiveSample(payload, contentType);
            return ResponseEntity.noContent().build();
        }
        voiceReg.attachSample(tempId, payload, contentType);
        return ResponseEntity.noContent().build();
    }

    @GetMapping("/voices/active/npz")
    public ResponseEntity<byte[]> activeVoiceNpz(
            @RequestHeader(value = "If-None-Match", required = false) String ifNoneMatch) {
        var meta = voiceProfiles.activeNpzMeta();
        String sha = (String) meta.get("sha256");
        String etag = "\"" + sha + "\"";
        if (ifNoneMatch != null && AgentBlobController.stripEtag(ifNoneMatch).equalsIgnoreCase(sha)) {
            return ResponseEntity.status(HttpStatus.NOT_MODIFIED).eTag(etag).build();
        }
        long id = ((Number) meta.get("id")).longValue();
        return ResponseEntity.ok()
                .eTag(etag)
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .body(voiceProfiles.npz(id));
    }

    // ------------------------------------------------------------------ 시선 보정

    @PutMapping(value = "/calibs/{tempId}/npz", consumes = MediaType.APPLICATION_OCTET_STREAM_VALUE)
    public ResponseEntity<Void> putCalibNpz(@PathVariable String tempId, @RequestBody byte[] payload,
                                            @RequestHeader(value = "X-Screen", required = false) String xScreen) {
        int[] wh = parseScreen(xScreen);
        calibReg.attachNpz(tempId, payload, wh[0], wh[1]);
        return ResponseEntity.noContent().build();
    }

    /** 활성 보정 npz — X-Screen 을 주면 학습 해상도와 대조해 불일치 시 409 를 돌려준다. */
    @GetMapping("/calibs/active/npz")
    public ResponseEntity<byte[]> activeCalibNpz(
            @RequestHeader(value = "If-None-Match", required = false) String ifNoneMatch,
            @RequestHeader(value = "X-Screen", required = false) String xScreen) {
        var meta = calibProfiles.activeNpzMeta();
        if (xScreen != null && !xScreen.isBlank()) {
            int[] wh = parseScreen(xScreen);
            Integer w = (Integer) meta.get("screenW");
            Integer h = (Integer) meta.get("screenH");
            if (w != null && h != null && (w != wh[0] || h != wh[1])) {
                throw new ApiException(ErrorCode.CALIB_RESOLUTION_MISMATCH,
                        "사용 중인 보정은 " + w + "x" + h + " 해상도에서 만들어졌습니다. 시선 보정을 다시 진행해 주세요");
            }
        }
        String sha = (String) meta.get("sha256");
        String etag = "\"" + sha + "\"";
        if (ifNoneMatch != null && AgentBlobController.stripEtag(ifNoneMatch).equalsIgnoreCase(sha)) {
            return ResponseEntity.status(HttpStatus.NOT_MODIFIED).eTag(etag).build();
        }
        long id = ((Number) meta.get("id")).longValue();
        return ResponseEntity.ok()
                .eTag(etag)
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .body(calibProfiles.npz(id));
    }

    /** "1920x1080" → [1920, 1080]. calib npz 업로드에는 필수다. */
    private static int[] parseScreen(String xScreen) {
        if (xScreen == null || xScreen.isBlank()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "calib 업로드에는 X-Screen 헤더(예: 1920x1080)가 필요합니다");
        }
        String[] parts = xScreen.trim().toLowerCase().split("x");
        if (parts.length == 2) {
            try {
                int w = Integer.parseInt(parts[0].trim());
                int h = Integer.parseInt(parts[1].trim());
                if (w > 0 && h > 0) {
                    return new int[]{w, h};
                }
            } catch (NumberFormatException ignored) {
            }
        }
        throw new ApiException(ErrorCode.INVALID_REQUEST, "X-Screen 형식은 '1920x1080' 이어야 합니다");
    }
}
