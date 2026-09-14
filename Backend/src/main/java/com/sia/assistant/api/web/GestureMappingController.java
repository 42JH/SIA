package com.sia.assistant.api.web;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.common.JsonBody;
import com.sia.assistant.config.DataDirs;
import com.sia.assistant.registration.RegistrationMedia;
import com.sia.assistant.settings.GestureService;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;

/**
 * 제스처 매핑 REST (와이어프레임 제스처 섹션).
 *  - 목록은 ★페이지네이션 (?kind&custom&hands&motion&dangling&page&size) — FE 로딩 성능 (회의 확정).
 *  - 켜기/끄기(PATCH {enabled})·수정(PUT)·삭제(DELETE /{id})·등록 영상(GET /{id}/video)·템플릿 백업(GET /{id}/npz).
 * 커스텀 제스처 저장(신규 등록)은 WS macro_assign 경로다 — 여기서는 제공하지 않는다.
 */
@RestController
@RequestMapping("/api/gestures")
public class GestureMappingController {

    private final GestureService gestureService;
    private final DataDirs dataDirs;
    private final ObjectMapper om;

    public GestureMappingController(GestureService gestureService, DataDirs dataDirs, ObjectMapper om) {
        this.gestureService = gestureService;
        this.dataDirs = dataDirs;
        this.om = om;
    }

    @GetMapping
    public Map<String, Object> list(
            @RequestParam(name = "kind", required = false) String kind,
            @RequestParam(name = "custom", required = false) Boolean custom,
            @RequestParam(name = "hands", required = false) Integer hands,
            @RequestParam(name = "motion", required = false) String motion,
            @RequestParam(name = "dangling", defaultValue = "false") boolean dangling,
            @RequestParam(name = "page", defaultValue = "0") int page,
            @RequestParam(name = "size", defaultValue = "20") int size) {
        GestureService.Page result = gestureService.list(kind, custom, hands, motion, dangling, page, size);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("page", result.page());
        out.put("pageSize", result.pageSize());
        out.put("total", result.total());
        out.put("items", result.items());
        return out;
    }

    @GetMapping("/{id}")
    public Map<String, Object> get(@PathVariable long id) {
        return gestureService.getOne(id);
    }

    /**
     * 등록 때 촬영한 영상(동적, webm) 또는 사진(정적, jpg) — 목록·상세의 미리보기.
     * 경로는 motion 과 무관하게 하나다. Content-Type 은 보관본의 확장자가 정한다.
     * ★ 사용자 카메라 영상·사진, PC 밖 반출 금지.
     */
    @GetMapping("/{id}/video")
    public ResponseEntity<Resource> video(@PathVariable long id) {
        String fileName = gestureService.videoPath(id);
        if (fileName == null || fileName.isBlank()) {
            return ResponseEntity.notFound().build();
        }
        Path base = dataDirs.gestures().toAbsolutePath().normalize();
        Path target = base.resolve(fileName).normalize();
        if (!target.startsWith(base) || !Files.isRegularFile(target)) {
            return ResponseEntity.notFound().build();
        }
        return ResponseEntity.ok()
                .contentType(RegistrationMedia.contentTypeOf(fileName))
                .body(new FileSystemResource(target));
    }

    /** 템플릿 npz 백업 다운로드 — 프로필 백업(GET /api/voices/{id}/npz)과 같은 역할. 기본 제공 제스처는 404. */
    @GetMapping("/{id}/npz")
    public ResponseEntity<byte[]> npz(@PathVariable long id) {
        gestureService.npzMeta(id); // 404 GESTURE_NOT_FOUND / BLOB_NOT_FOUND
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, "attachment; filename=\"gesture-" + id + ".npz\"")
                .contentType(MediaType.APPLICATION_OCTET_STREAM)
                .body(gestureService.npz(id));
    }

    /** 켜기/끄기 토글 — 본문 {"enabled": true|false}. 기본 제스처에도 허용된다. */
    @PatchMapping("/{id}")
    public ResponseEntity<Void> toggle(@PathVariable long id, @RequestBody String raw) {
        JsonNode body = JsonBody.parseObject(om, raw);
        if (!body.has("enabled") || !body.path("enabled").isBoolean()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "enabled(true|false) 가 필요합니다");
        }
        gestureService.setEnabled(id, body.path("enabled").asBoolean());
        return ResponseEntity.noContent().build();
    }

    /**
     * 제스처 수정 — {name?, label?, description?, repeatable?, steps?}.
     * 기본 제공 제스처는 steps · repeatable 만 받는다 (모양과 표시 문구는 BE 소유). 빈 steps 는 기능 해제다.
     * 동작(영상) 재촬영은 WS reg_start {replaceGestureId} 경로다.
     */
    @PutMapping("/{id}")
    public Map<String, Object> update(@PathVariable long id, @RequestBody String raw) {
        JsonNode body = JsonBody.parseObject(om, raw);
        List<GestureService.Step> steps = null;
        if (body.has("steps")) {
            steps = new ArrayList<>();
            for (JsonNode s : body.path("steps")) {
                Map<String, Object> args = s.hasNonNull("args")
                        ? om.convertValue(s.path("args"), new TypeReference<Map<String, Object>>() { })
                        : Map.of();
                steps.add(new GestureService.Step(s.path("tool").asText(""), args,
                        s.hasNonNull("delayMs") ? s.path("delayMs").asInt() : null));
            }
        }
        gestureService.update(id,
                body.hasNonNull("name") ? body.path("name").asText() : null,
                body.hasNonNull("label") ? body.path("label").asText() : null,
                body.hasNonNull("description") ? body.path("description").asText() : null,
                body.hasNonNull("repeatable") ? body.path("repeatable").asBoolean() : null,
                steps);
        return gestureService.getOne(id);
    }

    /** 커스텀 제스처 삭제 — id 기준 (동명·다른 컨텍스트와의 모호성 제거). */
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> remove(@PathVariable long id) {
        gestureService.removeCustom(id);
        return ResponseEntity.noContent().build();
    }
}
