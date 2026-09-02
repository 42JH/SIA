package com.sia.assistant.control.process;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.logging.ToolCallRecorder;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;

/**
 * app.launch 의 실행부. 실행 가능한 것은 app_target 에 등록된 항목뿐이다 — 사용자가 등록한 앱과
 * BE 가 시드한 Windows 기본 앱(DefaultAppTargets: 메모장·계산기)이고,
 * LLM 이 임의 경로를 실행할 수 있는 칸은 어디에도 없다.
 */
@Service
public class AppLaunchService {

    private static final Logger log = LoggerFactory.getLogger(AppLaunchService.class);

    private final JdbcTemplate jdbc;
    private final ToolCallRecorder recorder;

    public AppLaunchService(JdbcTemplate jdbc, ToolCallRecorder recorder) {
        this.jdbc = jdbc;
        this.recorder = recorder;
    }

    public Map<String, Object> launch(String appKey) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT id, exec_path, args, enabled FROM app_target WHERE app_key = ?", appKey);
        if (rows.isEmpty() || ((Number) rows.get(0).get("enabled")).intValue() != 1) {
            throw new BlockedException(ErrorCode.APP_NOT_REGISTERED,
                    "등록되지 않은 앱입니다. app.list로 실행 가능한 앱을 확인하세요");
        }
        Map<String, Object> row = rows.get(0);
        long id = ((Number) row.get("id")).longValue();
        String execPath = (String) row.get("exec_path");
        String args = row.get("args") == null ? "" : (String) row.get("args");

        Path exe = Path.of(execPath);
        if (!Files.exists(exe)) {
            throw new BlockedException(ErrorCode.APP_PATH_INVALID,
                    "앱 실행 파일을 찾을 수 없습니다. 설정에서 경로를 다시 등록해주세요");
        }

        // 이 스레드의 다음 tool_call 기록에 app_target_id 를 실어준다 (recorder 가 finally 에서 지운다)
        recorder.hintAppTarget(id);

        List<String> command = new ArrayList<>();
        command.add(exe.toString());
        command.addAll(tokenize(args));
        ProcessBuilder pb = new ProcessBuilder(command);
        Path parent = exe.getParent();
        if (parent != null) {
            pb.directory(parent.toFile());
        }
        Process process;
        try {
            process = pb.start();
        } catch (IOException e) {
            log.warn("앱 실행 실패: {} ({})", appKey, execPath, e);
            throw new ApiException(ErrorCode.INTERNAL_ERROR, "앱 실행에 실패했습니다. 잠시 후 다시 시도해주세요",
                    e.getMessage());
        }
        // pid 는 참고값이다 (흐름도 02 "ok {pid}"). 후속 창 조작은 pid 가 아니라 context.get 의 ref 로 한다.
        Map<String, Object> out = new java.util.LinkedHashMap<>();
        out.put("ok", true);
        out.put("pid", process.pid());
        return out;
    }

    /** 공백 분리 + 큰따옴표 구간 보존. args 는 사용자가 등록한 문자열이다. */
    static List<String> tokenize(String args) {
        List<String> out = new ArrayList<>();
        if (args == null || args.isBlank()) {
            return out;
        }
        StringBuilder cur = new StringBuilder();
        boolean quoted = false;
        for (int i = 0; i < args.length(); i++) {
            char c = args.charAt(i);
            if (c == '"') {
                quoted = !quoted;
            } else if (!quoted && Character.isWhitespace(c)) {
                if (cur.length() > 0) {
                    out.add(cur.toString());
                    cur.setLength(0);
                }
            } else {
                cur.append(c);
            }
        }
        if (cur.length() > 0) {
            out.add(cur.toString());
        }
        return out;
    }
}
