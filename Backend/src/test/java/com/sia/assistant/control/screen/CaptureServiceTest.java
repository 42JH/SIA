package com.sia.assistant.control.screen;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.ws.FeHub;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.ArgumentCaptor;

/**
 * 캡처 결과물 저장·표시 규칙 (흐름도 02 "저장·표시는 BE 소유") — 화면 읽기(GDI)는 스텁으로 대체한다.
 * 두 점 영역 캡처(screen.capture_region)의 정규화·잘라내기 규칙도 여기서 검증한다.
 */
class CaptureServiceTest {

    private static final Rectangle SCREEN = new Rectangle(0, 0, 8, 6);
    private static final Rectangle WINDOW = new Rectangle(2, 1, 4, 3);

    /** GDI 대신 쓰는 스텁 — 마지막으로 요청받은 사각형을 기억해 정규화·잘라내기를 검증한다. */
    private static final class RecordingGrabber implements ScreenGrabber {
        Rectangle last;

        @Override
        public Rectangle virtualScreen() {
            return SCREEN;
        }

        @Override
        public Rectangle windowRect(long hwnd) {
            return hwnd == 42L ? WINDOW : null;
        }

        @Override
        public BufferedImage grab(Rectangle rect) {
            last = rect;
            return new BufferedImage(rect.width, rect.height, BufferedImage.TYPE_INT_RGB);
        }
    }

    private Path dir;
    private FeHub feHub;
    private RecordingGrabber grabber;
    private CaptureService service;

    @BeforeEach
    void setUp(@TempDir Path tmp) {
        dir = tmp.resolve("Pictures").resolve("SIA");
        feHub = mock(FeHub.class);
        grabber = new RecordingGrabber();
        service = new CaptureService(grabber, feHub, dir);
    }

    @Test
    @DisplayName("winRef 없이 부르면 전체 화면을 PNG 로 저장하고 FE 에 capture_saved 를 push 한다")
    void capturesWholeScreenAndNotifiesFe() {
        Map<String, Object> out = service.capture(null);

        Path saved = Path.of((String) out.get("path"));
        assertThat(saved).exists();
        assertThat(saved.getParent()).isEqualTo(dir.toAbsolutePath());
        assertThat(saved.getFileName().toString()).matches("capture_\\d{8}_\\d{6}\\.png");
        assertThat(out).containsEntry("width", 8).containsEntry("height", 6)
                .containsEntry("url", "/api/captures/" + saved.getFileName());

        @SuppressWarnings("unchecked")
        ArgumentCaptor<Map<String, Object>> body = ArgumentCaptor.forClass(Map.class);
        verify(feHub).send(eq("capture_saved"), body.capture());
        assertThat(body.getValue()).isEqualTo(out);
    }

    @Test
    @DisplayName("창을 지정하면 그 창의 사각형만 캡처한다")
    void capturesWindowRect() {
        Map<String, Object> out = service.capture(42L);

        assertThat(out).containsEntry("width", 4).containsEntry("height", 3);
    }

    @Test
    @DisplayName("죽은 창은 REF_NOT_FOUND 로 차단된다")
    void deadWindowIsBlocked() {
        assertThatThrownBy(() -> service.capture(7L))
                .isInstanceOfSatisfying(BlockedException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.REF_NOT_FOUND));
    }

    @Test
    @DisplayName("같은 초에 두 번 저장하면 _2 를 붙여 덮어쓰지 않는다")
    void secondCaptureInSameSecondGetsSuffix() {
        Path first = Path.of((String) service.capture(null).get("path"));
        Path second = Path.of((String) service.capture(null).get("path"));

        assertThat(second).isNotEqualTo(first);
        assertThat(second.getFileName().toString()).matches("capture_\\d{8}_\\d{6}_2\\.png");
        assertThat(first).exists();
        assertThat(second).exists();
    }

    @Test
    @DisplayName("서빙 경로는 저장 폴더 안의 PNG 만 허용한다 — 이름 패턴·디렉터리 이탈 차단")
    void resolveRejectsBadNames() throws Exception {
        Path saved = Path.of((String) service.capture(null).get("path"));
        Files.writeString(dir.getParent().resolve("secret.png"), "x");

        assertThat(service.resolve(saved.getFileName().toString())).isEqualTo(saved.toAbsolutePath());
        assertThat(service.resolve("../secret.png")).isNull();
        assertThat(service.resolve("nope.png")).isNull();
        assertThat(service.resolve("capture.txt")).isNull();
        assertThat(service.resolve(null)).isNull();
    }

    // ------------------------------------------------------------ screen.capture_region

    @Test
    @DisplayName("우상단·좌하단 두 점을 주면 두 점이 감싸는 사각형만 캡처하고 FE 에 capture_saved 를 push 한다")
    void capturesRegionBetweenTopRightAndBottomLeft() {
        // 우상단 (6, 1) · 좌하단 (2, 4) → x 2..6, y 1..4 (반열림) → 4×3
        Map<String, Object> out = service.captureRegion(6, 1, 2, 4);

        assertThat(grabber.last).isEqualTo(new Rectangle(2, 1, 4, 3));
        assertThat(out).containsEntry("width", 4).containsEntry("height", 3);
        Path saved = Path.of((String) out.get("path"));
        assertThat(saved).exists();
        assertThat(out).containsEntry("url", "/api/captures/" + saved.getFileName());
        verify(feHub).send(eq("capture_saved"), eq(out));
    }

    @Test
    @DisplayName("두 점의 순서가 바뀌어도(좌상단·우하단, 좌하단·우상단) 같은 사각형으로 정규화한다")
    void regionCornersMayComeInAnyOrder() {
        service.captureRegion(2, 1, 6, 4);
        assertThat(grabber.last).isEqualTo(new Rectangle(2, 1, 4, 3));

        service.captureRegion(2, 4, 6, 1);
        assertThat(grabber.last).isEqualTo(new Rectangle(2, 1, 4, 3));
    }

    @Test
    @DisplayName("가상 스크린 밖으로 나간 부분은 잘라내고 잘라낸 뒤의 실제 크기를 돌려준다")
    void regionIsClippedToVirtualScreen() {
        // 좌상 방향으로 넘침 — (-3, -2) ~ (5, 3) → (0, 0) ~ (5, 3)
        Map<String, Object> out = service.captureRegion(5, -2, -3, 3);
        assertThat(grabber.last).isEqualTo(new Rectangle(0, 0, 5, 3));
        assertThat(out).containsEntry("width", 5).containsEntry("height", 3);

        // 우하 방향으로 넘침 — (4, 2) ~ (20, 30) → (4, 2) ~ (8, 6)
        service.captureRegion(20, 2, 4, 30);
        assertThat(grabber.last).isEqualTo(new Rectangle(4, 2, 4, 4));
    }

    @Test
    @DisplayName("두 점이 한 줄에 놓이거나 같으면 영역이 비어 INVALID_REQUEST 다 — 캡처도 통지도 없다")
    void emptyRegionIsRejected() {
        assertThatThrownBy(() -> service.captureRegion(3, 1, 3, 4))
                .isInstanceOfSatisfying(ApiException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.INVALID_REQUEST))
                .hasMessageContaining("비어 있습니다");
        assertThatThrownBy(() -> service.captureRegion(2, 2, 2, 2))
                .isInstanceOf(ApiException.class);

        assertThat(grabber.last).isNull();
        verifyNoInteractions(feHub);
    }

    @Test
    @DisplayName("화면과 전혀 겹치지 않는 영역은 INVALID_REQUEST 다")
    void offscreenRegionIsRejected() {
        assertThatThrownBy(() -> service.captureRegion(-5, -10, -10, -5))
                .isInstanceOfSatisfying(ApiException.class,
                        e -> assertThat(e.code).isEqualTo(ErrorCode.INVALID_REQUEST))
                .hasMessageContaining("화면 밖");

        assertThat(grabber.last).isNull();
        verifyNoInteractions(feHub);
    }
}
