package com.sia.assistant.control.files;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import org.springframework.stereotype.Service;

/**
 * files.save 의 실행부 — 저장 위치는 문서 폴더(~/Documents)/SIA/ 하나뿐이다.
 * 파일명은 경로 구분자·상위 이동을 정제해 폴더를 벗어날 수 없게 한다. 중복이면 " (1)" 접미사.
 */
@Service
public class FileSaveService {

    public Map<String, Object> save(String name, String content) {
        String clean = sanitize(name);
        if (clean.isEmpty()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "저장할 파일 이름이 올바르지 않습니다");
        }
        Path dir = documentsDir();
        try {
            Files.createDirectories(dir);
            Path target = dedupe(dir, clean);
            Files.writeString(target, content == null ? "" : content, StandardCharsets.UTF_8);
            return Map.of("path", target.toAbsolutePath().toString());
        } catch (IOException e) {
            throw new ApiException(ErrorCode.INTERNAL_ERROR, "파일 저장에 실패했습니다. 잠시 후 다시 시도해주세요",
                    e.getMessage());
        }
    }

    private static Path documentsDir() {
        return Path.of(System.getProperty("user.home"), "Documents", "SIA");
    }

    /** 경로 구분자·'..'·윈도우 금지 문자·제어 문자 제거, 끝의 점·공백 제거(Windows 규칙). */
    static String sanitize(String name) {
        if (name == null) {
            return "";
        }
        String s = name.trim()
                .replace("\\", "")
                .replace("/", "")
                .replace("..", "");
        StringBuilder sb = new StringBuilder(s.length());
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c < 0x20 || c == '<' || c == '>' || c == ':' || c == '"' || c == '|' || c == '?' || c == '*') {
                continue;
            }
            sb.append(c);
        }
        String out = sb.toString();
        // Windows 는 끝의 점·공백을 조용히 제거해 다른 파일이 된다 — 우리가 먼저 제거한다
        int end = out.length();
        while (end > 0 && (out.charAt(end - 1) == '.' || out.charAt(end - 1) == ' ')) {
            end--;
        }
        return out.substring(0, end);
    }

    /** 같은 이름이 있으면 확장자 앞에 " (1)", " (2)" ... 를 붙인다. */
    private static Path dedupe(Path dir, String fileName) {
        Path candidate = dir.resolve(fileName);
        if (!Files.exists(candidate)) {
            return candidate;
        }
        int dot = fileName.lastIndexOf('.');
        String base = dot > 0 ? fileName.substring(0, dot) : fileName;
        String ext = dot > 0 ? fileName.substring(dot) : "";
        for (int i = 1; ; i++) {
            Path next = dir.resolve(base + " (" + i + ")" + ext);
            if (!Files.exists(next)) {
                return next;
            }
        }
    }
}
