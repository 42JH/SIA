package com.sia.assistant.control.files;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import java.awt.Desktop;
import java.awt.GraphicsEnvironment;
import java.lang.ProcessBuilder.Redirect;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Locale;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * files.open 의 실행부 — 파일을 연다.
 * 제스처 "파일 실행" 블록의 목적지다: 절대 경로는 등록 시 FE 파일 선택기가 확정해
 * gesture_step.args_json 의 {"path": "..."} 로 저장돼 있다 (와이어프레임 제스처 등록 5-1/5-2).
 * 열기만 한다 — 쓰기·삭제가 없어 확인 게이트(C) 대상이 아니다.
 *
 * <p>★ 실행 파일과 문서는 수단이 다르다. 문서는 Windows 기본 연결 프로그램에 맡기지만 exe 는 직접 실행한다.
 * Desktop.open 은 ShellExecuteW(NULL, "open", path, NULL, NULL, SW_SHOWNORMAL) 이고 lpDirectory 가
 * NULL 이라, 자식이 BE 의 작업 디렉터리를 물려받는다 — exe 옆에 애셋을 두는 앱은 떠도 제 파일을 못 찾는다.
 * app.launch(AppLaunchService)가 쓰는 수단과 같은 것을 쓴다.
 */
@Service
public class FileOpenService {

    private static final Logger log = LoggerFactory.getLogger(FileOpenService.class);

    // 열기 실패 사유는 tool_result.message 로 사용자에게 그대로 보이므로 한 문장으로 고정한다.
    // 진짜 사유는 ApiException.detail 로 넘긴다 — ToolGate 가 콘솔 로그에만 덧붙인다.
    private static final String OPEN_FAILED = "파일을 열지 못했습니다. 잠시 후 다시 시도해주세요";

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
        Path absolute = target.toAbsolutePath();
        if (isExecutable(absolute)) {
            launch(absolute);
        } else {
            shellOpen(absolute);
        }
        return Map.of("opened", true, "path", absolute.toString());
    }

    /** exe 만 직접 실행한다 — 바로 가기(.lnk)·배치(.bat)는 셸이 풀어줘야 하므로 기본 연결 프로그램 쪽이다. */
    static boolean isExecutable(Path target) {
        Path name = target.getFileName();
        return name != null && name.toString().toLowerCase(Locale.ROOT).endsWith(".exe");
    }

    /** app.launch 와 같은 수단 — 작업 디렉터리를 exe 자신의 폴더로 잡아준다. */
    static ProcessBuilder launcher(Path exe) {
        ProcessBuilder pb = new ProcessBuilder(exe.toString());
        Path parent = exe.getParent();
        if (parent != null) {
            pb.directory(parent.toFile());
        }
        // 기본값인 파이프로 두면 아무도 읽지 않아, 출력이 많은 앱은 파이프가 차는 순간 멈춘다
        pb.redirectOutput(Redirect.DISCARD);
        pb.redirectError(Redirect.DISCARD);
        return pb;
    }

    private void launch(Path exe) {
        try {
            Process process = launcher(exe).start();
            log.info("files.open 실행 파일 기동: {} (pid={})", exe, process.pid());
        } catch (Exception e) {
            throw new ApiException(ErrorCode.INTERNAL_ERROR, OPEN_FAILED, e.toString());
        }
    }

    /** 문서는 Windows 기본 연결 프로그램에 맡긴다. 쓸 수 없는 환경이면 사유를 detail 에 남긴다. */
    private void shellOpen(Path target) {
        if (GraphicsEnvironment.isHeadless() || !Desktop.isDesktopSupported()
                || !Desktop.getDesktop().isSupported(Desktop.Action.OPEN)) {
            throw new ApiException(ErrorCode.INTERNAL_ERROR, OPEN_FAILED,
                    "이 환경에서는 기본 연결 프로그램으로 열 수 없습니다 (headless="
                            + GraphicsEnvironment.isHeadless() + ")");
        }
        try {
            Desktop.getDesktop().open(target.toFile());
        } catch (Exception e) {
            throw new ApiException(ErrorCode.INTERNAL_ERROR, OPEN_FAILED, e.toString());
        }
    }
}
