package com.sia.assistant.registration;

import java.util.Locale;
import org.springframework.http.MediaType;

/**
 * 등록 촬영본의 포맷 규칙 한 곳 — 동적 제스처는 webm, 정적 제스처는 jpg 다.
 *
 * <p>정적 제스처는 회차당 프레임이 한 장이라 ffmpeg 를 태울 이유가 없다. reg_frame 이 처음부터
 * JPEG 를 보내므로 그 한 장을 그대로 보관한다 — 인코딩 실패 경로가 없고, FE 가 {@code <img>} 로
 * 띄울 수 있다(1프레임 webm 은 정지 화면인지 로딩 실패인지 사용자가 구분하지 못한다).
 *
 * <p>previews/ · gestures/ 두 디렉터리와 두 서빙 엔드포인트가 확장자를 각자 가정하고 있었어서,
 * 확장자를 아는 자리를 여기 하나로 모았다.
 */
public final class RegistrationMedia {

    static final String WEBM = ".webm";
    static final String JPG = ".jpg";

    /** reg_recorded 의 mediaType — FE 가 {@code <video>} / {@code <img>} 를 고르는 값이다. */
    static final String VIDEO = "VIDEO";
    static final String IMAGE = "IMAGE";

    private static final MediaType WEBM_TYPE = MediaType.parseMediaType("video/webm");

    /** 이 motion 으로 찍은 촬영본의 확장자. motion 이 없으면(옛 등록) 동적으로 본다. */
    static String extensionFor(String motion) {
        return isStatic(motion) ? JPG : WEBM;
    }

    static boolean isStatic(String motion) {
        return motion != null && motion.trim().equalsIgnoreCase("STATIC");
    }

    /** 등록 촬영본으로 인정하는 파일인가 — previews/ 청소와 서빙이 같은 기준을 쓴다. */
    public static boolean isMediaFile(String fileName) {
        String lower = fileName == null ? "" : fileName.toLowerCase(Locale.ROOT);
        return lower.endsWith(WEBM) || lower.endsWith(JPG);
    }

    /** 보관본의 확장자가 Content-Type 을 정한다. 아는 확장자가 아니면 webm 으로 둔다(옛 보관본). */
    public static MediaType contentTypeOf(String fileName) {
        String lower = fileName == null ? "" : fileName.toLowerCase(Locale.ROOT);
        return lower.endsWith(JPG) ? MediaType.IMAGE_JPEG : WEBM_TYPE;
    }

    private RegistrationMedia() {
    }
}
