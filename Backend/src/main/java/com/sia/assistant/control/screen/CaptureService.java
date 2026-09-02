package com.sia.assistant.control.screen;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.ws.FeHub;
import java.awt.Rectangle;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

/**
 * 캡처 결과물의 저장·표시 — 흐름도 02 경계 규칙 "저장·표시는 BE 소유".
 * screen.capture(화면 · 창) · screen.capture_region(두 점이 감싸는 영역) 도구가 부른다: 화면을 읽어 ~/Pictures/SIA/ 에 PNG 로 저장하고,
 * FE 에 capture_saved {path, url, width, height} 를 push 한다. 파일은 GET /api/captures/{file} 로 서빙된다.
 * 파일명은 capture_yyyyMMdd_HHmmss.png 이고 같은 초에 두 번 찍히면 _2, _3 을 붙인다.
 */
@Service
public class CaptureService {

    private static final Pattern FILE_NAME = Pattern.compile("^[A-Za-z0-9_-]+\\.png$");
    private static final DateTimeFormatter STAMP = DateTimeFormatter.ofPattern("yyyyMMdd_HHmmss");
    private static final String REF_NOT_FOUND_MESSAGE = "대상을 찾을 수 없습니다. context.get으로 목록을 다시 확인하세요";
    private static final String EMPTY_REGION_MESSAGE =
            "캡처 영역이 비어 있습니다. 두 점의 x 좌표끼리, y 좌표끼리 서로 달라야 합니다";
    private static final String OFFSCREEN_REGION_MESSAGE =
            "캡처 영역이 화면 밖입니다. 좌표는 가상 스크린 물리 픽셀이어야 합니다";

    private final ScreenGrabber grabber;
    private final FeHub feHub;
    private final Path dir;

    @Autowired
    public CaptureService(ScreenGrabber grabber, FeHub feHub) {
        this(grabber, feHub, Path.of(System.getProperty("user.home"), "Pictures", "SIA"));
    }

    CaptureService(ScreenGrabber grabber, FeHub feHub, Path dir) {
        this.grabber = grabber;
        this.feHub = feHub;
        this.dir = dir;
    }

    /**
     * hwnd 가 null 이면 전체 가상 스크린, 아니면 그 창의 화면 영역을 캡처해 저장한다.
     * @return {path, url, width, height} — 도구 반환값이자 FE capture_saved 페이로드
     */
    public Map<String, Object> capture(Long hwndOrNull) {
        Rectangle rect;
        if (hwndOrNull == null) {
            rect = grabber.virtualScreen();
        } else {
            rect = grabber.windowRect(hwndOrNull);
            if (rect == null) {
                throw new BlockedException(ErrorCode.REF_NOT_FOUND, REF_NOT_FOUND_MESSAGE);
            }
        }
        return save(grabber.grab(rect));
    }

    /**
     * 우상단 (x1, y1) · 좌하단 (x2, y2) 두 점이 감싸는 사각형을 캡처해 저장한다 — screen.capture_region.
     * 두 점의 순서는 가리지 않는다(어느 두 대각 모서리든 같은 사각형으로 정규화). 너비·높이는 |x1-x2|·|y1-y2| 의 반열림 구간이고,
     * 가상 스크린 밖은 잘라낸다. 두 점이 한 줄에 놓이거나 잘라낸 뒤 남는 영역이 없으면 INVALID_REQUEST(ToolGate 가 FAILED 로).
     * @return {path, url, width, height} — width · height 는 잘라낸 뒤의 실제 크기
     */
    public Map<String, Object> captureRegion(int x1, int y1, int x2, int y2) {
        long width = Math.abs((long) x1 - x2);
        long height = Math.abs((long) y1 - y2);
        if (width == 0 || height == 0) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, EMPTY_REGION_MESSAGE);
        }
        Rectangle requested = new Rectangle(Math.min(x1, x2), Math.min(y1, y2),
                (int) Math.min(width, Integer.MAX_VALUE), (int) Math.min(height, Integer.MAX_VALUE));
        Rectangle clipped = requested.intersection(grabber.virtualScreen());
        if (clipped.isEmpty()) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, OFFSCREEN_REGION_MESSAGE);
        }
        return save(grabber.grab(clipped));
    }

    /** PNG 저장 + FE 통지. 저장 위치는 사진 폴더(~/Pictures/SIA) 하나뿐이다. */
    Map<String, Object> save(BufferedImage image) {
        try {
            Files.createDirectories(dir);
            Path target = dedupe("capture_" + LocalDateTime.now().format(STAMP));
            javax.imageio.ImageIO.write(image, "png", target.toFile());
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("path", target.toAbsolutePath().toString());
            out.put("url", "/api/captures/" + target.getFileName());
            out.put("width", image.getWidth());
            out.put("height", image.getHeight());
            feHub.send("capture_saved", out);
            return out;
        } catch (IOException e) {
            throw new ApiException(ErrorCode.INTERNAL_ERROR, "캡처 저장에 실패했습니다. 잠시 후 다시 시도해주세요",
                    e.getMessage());
        }
    }

    /** GET /api/captures/{file} — 이름 패턴과 디렉터리 이탈을 검사한다. 없으면 null. */
    public Path resolve(String fileName) {
        if (fileName == null || !FILE_NAME.matcher(fileName).matches()) {
            return null;
        }
        Path base = dir.toAbsolutePath().normalize();
        Path target = base.resolve(fileName).normalize();
        if (!target.startsWith(base) || !Files.isRegularFile(target)) {
            return null;
        }
        return target;
    }

    private Path dedupe(String base) {
        Path candidate = dir.resolve(base + ".png");
        if (!Files.exists(candidate)) {
            return candidate;
        }
        for (int i = 2; ; i++) {
            Path next = dir.resolve(base + "_" + i + ".png");
            if (!Files.exists(next)) {
                return next;
            }
        }
    }
}
