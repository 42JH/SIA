package com.sia.assistant.api.web;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sia.assistant.common.JsonBody;
import com.sia.assistant.profile.VoiceProfileService;
import com.sia.assistant.registration.VoiceRegistrationOrchestrator;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/**
 * 보이스 프로필 REST (와이어프레임 보이스 섹션) — 목록·이름 변경·사용으로 설정·완전 삭제·재생.
 * 등록 플로우 자체는 WS(voice_reg_start …)다 — 여기는 확정본 관리만 한다.
 */
@RestController
public class VoiceProfileController {

    private final VoiceProfileService voiceProfiles;
    private final VoiceRegistrationOrchestrator voiceReg;
    private final ObjectMapper om;

    public VoiceProfileController(VoiceProfileService voiceProfiles,
                                  VoiceRegistrationOrchestrator voiceReg, ObjectMapper om) {
        this.voiceProfiles = voiceProfiles;
        this.voiceReg = voiceReg;
        this.om = om;
    }

    /** 목록 — 사용 중 먼저. 프로필별 정확도(d7/d30/all)를 함께 준다 (롤백 판단 근거). */
    @GetMapping("/api/voices")
    public Map<String, Object> list() {
        return Map.of("items", voiceProfiles.list());
    }

    /** 샘플 오디오 재생 — 등록 녹음 또는 화자 인식 때의 마지막 발화. */
    @GetMapping("/api/voices/{id}/sample")
    public ResponseEntity<byte[]> sample(@PathVariable long id) {
        VoiceProfileService.Sample sample = voiceProfiles.sample(id);
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(sample.mime() == null ? "audio/webm" : sample.mime()))
                .body(sample.bytes());
    }

    /** npz 백업 다운로드 (attachment). ★ 생체 유사 데이터 — PC 밖 반출 금지, 백업 수단일 뿐이다. */
    @GetMapping("/api/voices/{id}/npz")
    public ResponseEntity<byte[]> npz(@PathVariable long id) {
        return ResponseEntity.ok()
                .header("Content-Disposition", "attachment; filename=\"voice-" + id + ".npz\"")
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .body(voiceProfiles.npz(id));
    }

    /** 이름 변경 — {"name": "..."} */
    @PatchMapping("/api/voices/{id}")
    public ResponseEntity<Void> rename(@PathVariable long id, @RequestBody String raw) {
        voiceProfiles.rename(id, JsonBody.parse(om, raw).path("name").asText(null));
        return ResponseEntity.noContent().build();
    }

    /** 사용으로 설정 — AI 에 voice_changed 가 나간다. */
    @PostMapping("/api/voices/{id}/activate")
    public Map<String, Object> activate(@PathVariable long id) {
        return voiceProfiles.activate(id);
    }

    /** 완전 삭제 — 사용 중이거나 마지막 1개면 409 (PROFILE_IN_USE). */
    @DeleteMapping("/api/voices/{id}")
    public ResponseEntity<Void> delete(@PathVariable long id) {
        voiceProfiles.delete(id);
        return ResponseEntity.noContent().build();
    }

    /** 등록 진행 중(커밋 전) 녹음 확인 화면의 재생용 — voice_review.sampleUrl 이 가리키는 곳. */
    @GetMapping("/api/voice-reg/{tempId}/sample")
    public ResponseEntity<byte[]> draftSample(@PathVariable String tempId) {
        VoiceProfileService.Sample sample = voiceReg.draftSample(tempId);
        return ResponseEntity.ok()
                .contentType(MediaType.parseMediaType(sample.mime() == null ? "audio/webm" : sample.mime()))
                .body(sample.bytes());
    }
}
