package com.sia.assistant.api.web;

import com.sia.assistant.settings.WipeService;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.RestController;

/** 전체 삭제 (DELETE /api/data) — 사용 기록·등록 데이터·설정을 초기 상태로 되돌린다. */
@RestController
public class DataController {

    private final WipeService wipeService;

    public DataController(WipeService wipeService) {
        this.wipeService = wipeService;
    }

    @DeleteMapping("/api/data")
    public ResponseEntity<Void> wipe() {
        wipeService.wipeAll();
        return ResponseEntity.noContent().build();
    }
}
