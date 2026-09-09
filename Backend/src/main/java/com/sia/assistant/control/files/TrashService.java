package com.sia.assistant.control.files;

import java.awt.Desktop;
import java.awt.GraphicsEnvironment;
import java.io.File;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Service;

/**
 * files.delete 의 실행부 — 휴지통 이동만 한다. 완전삭제 코드는 이 제품 어디에도 없다.
 * 개별 항목의 실패(부재·권한·미지원)는 failed 목록으로 수집하고 예외로 죽지 않는다.
 */
@Service
public class TrashService {

    public Map<String, Object> moveToTrash(List<String> paths) {
        int trashed = 0;
        List<String> failed = new ArrayList<>();
        List<String> in = paths == null ? List.of() : paths;

        boolean supported = !GraphicsEnvironment.isHeadless()
                && Desktop.isDesktopSupported()
                && Desktop.getDesktop().isSupported(Desktop.Action.MOVE_TO_TRASH);

        for (String path : in) {
            if (path == null || path.isBlank()) {
                failed.add("(빈 경로) — 경로가 비어 있습니다");
                continue;
            }
            File file = new File(path);
            if (!file.exists()) {
                failed.add(path + " — 파일을 찾을 수 없습니다");
                continue;
            }
            if (!supported) {
                failed.add(path + " — 이 환경에서는 휴지통 이동을 지원하지 않습니다");
                continue;
            }
            try {
                if (Desktop.getDesktop().moveToTrash(file)) {
                    trashed++;
                } else {
                    failed.add(path + " — 휴지통 이동에 실패했습니다");
                }
            } catch (Exception e) {
                String reason = e.getMessage() == null ? "휴지통 이동에 실패했습니다" : e.getMessage();
                failed.add(path + " — " + reason);
            }
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("trashed", trashed);
        out.put("failed", failed);
        return out;
    }
}
