package com.sia.assistant.api.web;

import com.sia.assistant.model.ModelManager;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 모델 파일 상태 조회와 재다운로드 요청 — 흐름도 01 [정정 3-2] "실패 시 FE 안내 + 재다운로드 유도" 의 유도 경로.
 * FE 가 model_error 를 받으면 사용자에게 묻고 POST /api/models/{name}/redownload 를 부른다.
 * 진행·완료·실패는 WS 로 돌아온다 (model_progress → model_downloaded | model_error).
 */
@RestController
@RequestMapping("/api/models")
public class ModelController {

    private final ModelManager modelManager;

    public ModelController(ModelManager modelManager) {
        this.modelManager = modelManager;
    }

    /** 모델별 상태 [{name, filename, fileReady, loaded, downloading}]. */
    @GetMapping
    public List<Map<String, Object>> list() {
        return modelManager.status();
    }

    /** 기존 파일을 버리고 다시 받는다. 비동기 — 202 로 접수만 알린다. 모르는 이름은 404. */
    @PostMapping("/{name}/redownload")
    public ResponseEntity<Map<String, Object>> redownload(@PathVariable String name) {
        modelManager.redownload(name);
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("name", name);
        body.put("status", "DOWNLOADING");
        return ResponseEntity.accepted().body(body);
    }
}
