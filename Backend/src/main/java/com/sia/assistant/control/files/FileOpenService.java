package com.sia.assistant.control.files;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import java.awt.Desktop;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import org.springframework.stereotype.Service;

/**
 * files.open 의 실행부 — 파일을 Windows 기본 연결 프로그램으로 연다.
 * 제스처 "파일 실행" 블록의 목적지다: 절대 경로는 등록 시 FE 파일 선택기가 확정해
 * gesture_step.args_json 의 {"path": "..."} 로 저장돼 있다 (와이어프레임 제스처 등록 5-1/5-2).
 * 열기만 한다 — 쓰기·삭제가 없어 확인 게이트(C) 대상이 아니다.
 */
@Service
public class FileOpenService {

    public Map<String, Object> open(String path) {
        if (path == null || path.isBlank()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "열 파일의 절대 경로가 필요합니다");
        }
        Path target = Path.of(path);
        if (!target.isAbsolute()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "파일 경로는 절대 경로여야 합니다: " + path);
        }
        if (!Files.exists(target)) {
            throw new BlockedException(ErrorCode.FILE_NOT_FOUND,
                    "파일을 찾을 수 없습니다. 제스처 설정에서 파일을 다시 지정해 주세요", path);
        }
        try {
            Desktop.getDesktop().open(target.toFile());
        } catch (Exception e) {
            throw new ApiException(ErrorCode.INTERNAL_ERROR, "파일을 열지 못했습니다. 잠시 후 다시 시도해주세요",
                    e.getMessage());
        }
        return Map.of("opened", true, "path", target.toAbsolutePath().toString());
    }
}
