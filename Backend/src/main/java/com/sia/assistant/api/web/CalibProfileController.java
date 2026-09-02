package com.sia.assistant.api.web;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sia.assistant.common.JsonBody;
import com.sia.assistant.profile.CalibProfileService;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 시선 보정 프로필 REST (와이어프레임 시선 섹션) — 목록·상세(산점도)·이름 변경·사용으로 설정·완전 삭제.
 * 보정 플로우 자체는 WS(calib_start …)다 — 여기는 확정본 관리만 한다.
 */
@RestController
@RequestMapping("/api/calibs")
public class CalibProfileController {

    private final CalibProfileService calibProfiles;
    private final ObjectMapper om;

    public CalibProfileController(CalibProfileService calibProfiles, ObjectMapper om) {
        this.calibProfiles = calibProfiles;
        this.om = om;
    }

    @GetMapping
    public Map<String, Object> list() {
        return Map.of("items", calibProfiles.list());
    }

    /** 상세 — 목록 필드 + pointsJson(시선 학습 결과 산점도). */
    @GetMapping("/{id}")
    public Map<String, Object> get(@PathVariable long id) {
        return calibProfiles.get(id);
    }

    /** npz 백업 다운로드 (attachment). */
    @GetMapping("/{id}/npz")
    public ResponseEntity<byte[]> npz(@PathVariable long id) {
        return ResponseEntity.ok()
                .header("Content-Disposition", "attachment; filename=\"calib-" + id + ".npz\"")
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .body(calibProfiles.npz(id));
    }

    /** 이름 변경 — {"name": "..."} */
    @PatchMapping("/{id}")
    public ResponseEntity<Void> rename(@PathVariable long id, @RequestBody String raw) {
        calibProfiles.rename(id, JsonBody.parse(om, raw).path("name").asText(null));
        return ResponseEntity.noContent().build();
    }

    /** 사용으로 설정 — AI 에 calib_changed 가 나간다. */
    @PostMapping("/{id}/activate")
    public Map<String, Object> activate(@PathVariable long id) {
        return calibProfiles.activate(id);
    }

    /** 완전 삭제 — 사용 중이거나 마지막 1개면 409 (PROFILE_IN_USE). */
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable long id) {
        calibProfiles.delete(id);
        return ResponseEntity.noContent().build();
    }
}
