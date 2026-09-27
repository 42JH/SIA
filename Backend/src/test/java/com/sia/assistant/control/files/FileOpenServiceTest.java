package com.sia.assistant.control.files;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import java.io.IOException;
import java.lang.ProcessBuilder.Redirect;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/**
 * files.open 이 실행 파일과 문서를 가르는 규칙 — exe 는 직접 실행하고 나머지는 기본 연결 프로그램에 맡긴다.
 * 실제로 프로세스를 띄우지 않고 실행 명령의 모양만 본다: 여기서 깨졌던 건 작업 디렉터리였다
 * (Desktop.open = ShellExecuteW 의 lpDirectory 가 NULL 이라 자식이 BE 의 작업 디렉터리를 물려받았다).
 */
class FileOpenServiceTest {

    private final FileOpenService service = new FileOpenService();

    @Test
    @DisplayName("exe 는 실행 파일로 가른다 — 대소문자를 가리지 않는다")
    void executableIsRecognized() {
        assertThat(FileOpenService.isExecutable(Path.of("C:\\tools\\PikaPet.exe"))).isTrue();
        assertThat(FileOpenService.isExecutable(Path.of("C:\\tools\\PIKAPET.EXE"))).isTrue();
    }

    @Test
    @DisplayName("문서·바로 가기·배치는 기본 연결 프로그램 쪽이다 — 셸이 풀어줘야 한다")
    void nonExecutablesGoToShell() {
        assertThat(FileOpenService.isExecutable(Path.of("C:\\docs\\회의록.txt"))).isFalse();
        assertThat(FileOpenService.isExecutable(Path.of("C:\\tools\\바로가기.lnk"))).isFalse();
        assertThat(FileOpenService.isExecutable(Path.of("C:\\tools\\실행.bat"))).isFalse();
        assertThat(FileOpenService.isExecutable(Path.of("C:\\tools\\exe"))).isFalse();
    }

    @Test
    @DisplayName("exe 는 자기 폴더를 작업 디렉터리로 실행한다 — BE 의 작업 디렉터리를 물려주지 않는다")
    void launcherRunsInTheExeOwnFolder(@TempDir Path dir) {
        Path exe = dir.resolve("tools").resolve("PikaPet.exe");
        ProcessBuilder pb = FileOpenService.launcher(exe);

        assertThat(pb.command()).containsExactly(exe.toString());
        assertThat(pb.directory()).isEqualTo(exe.getParent().toFile());
    }

    @Test
    @DisplayName("자식의 출력은 버린다 — 파이프에 두면 출력이 많은 앱이 파이프가 차는 순간 멈춘다")
    void launcherDiscardsChildOutput(@TempDir Path dir) {
        ProcessBuilder pb = FileOpenService.launcher(dir.resolve("PikaPet.exe"));

        assertThat(pb.redirectOutput()).isEqualTo(Redirect.DISCARD);
        assertThat(pb.redirectError()).isEqualTo(Redirect.DISCARD);
    }

    @Test
    @DisplayName("빈 경로·상대 경로는 INVALID_REQUEST 다")
    void pathMustBeAbsolute() {
        assertThatThrownBy(() -> service.open("  "))
                .isInstanceOf(ApiException.class)
                .hasMessage("열 파일의 절대 경로가 필요합니다");
        assertThatThrownBy(() -> service.open("tools\\PikaPet.exe"))
                .isInstanceOf(ApiException.class)
                .hasMessageStartingWith("파일 경로는 절대 경로여야 합니다");
    }

    @Test
    @DisplayName("없는 파일은 BLOCKED FILE_NOT_FOUND 다 — 실행 실패(FAILED)와 갈라 보고한다")
    void missingFileIsBlocked(@TempDir Path dir) {
        Path absent = dir.resolve("없는파일.exe").toAbsolutePath();

        assertThatThrownBy(() -> service.open(absent.toString()))
                .isInstanceOf(BlockedException.class)
                .extracting(e -> ((BlockedException) e).code)
                .isEqualTo(ErrorCode.FILE_NOT_FOUND);
    }

    @Test
    @DisplayName("실행 실패 사유는 detail 로 넘긴다 — 사용자 문장은 한 줄로 고정이다")
    void launchFailureKeepsTheRealReasonInDetail(@TempDir Path dir) throws IOException {
        // 디렉터리인데 이름만 exe — CreateProcess 가 거부한다
        Path notAnExe = Files.createDirectory(dir.resolve("PikaPet.exe")).toAbsolutePath();

        assertThatThrownBy(() -> service.open(notAnExe.toString()))
                .isInstanceOf(ApiException.class)
                .hasMessage("파일을 열지 못했습니다. 잠시 후 다시 시도해주세요")
                .extracting(e -> ((ApiException) e).detail)
                .asString()
                .isNotBlank();
    }
}
