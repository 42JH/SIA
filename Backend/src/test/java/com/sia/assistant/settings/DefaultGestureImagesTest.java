package com.sia.assistant.settings;

import static org.assertj.core.api.Assertions.assertThat;

import com.sia.assistant.registration.RegistrationMedia;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;

/**
 * 기본 제공 제스처의 예시 애셋 조회 — 확장자는 motion 이 정하고, 카탈로그 9종의 이름만 통과한다.
 * 테스트 애셋은 src/test/resources/seed/gestures/ 의 Open_Palm.jpg · Swipe_Left.webm 둘이다
 * (내용은 아무도 보지 않아 4바이트 표식만 들어 있다 — 계약은 존재 여부와 파일명뿐이다).
 */
class DefaultGestureImagesTest {

    @Test
    @DisplayName("정적은 jpg, 동적 스와이프는 webm 을 찾는다 — FE 가 motion 으로 <img>/<video> 를 고르기 때문")
    void extensionFollowsMotion() {
        assertThat(DefaultGestureImages.fileName("Open_Palm")).isEqualTo("Open_Palm.jpg");
        assertThat(DefaultGestureImages.fileName("Swipe_Left")).isEqualTo("Swipe_Left.webm");
    }

    @Test
    @DisplayName("애셋이 있는 이름만 파일명을 돌려준다 — 9장을 한꺼번에 넣지 않아도 넣은 것부터 뜬다")
    void assetPresenceDecides() {
        for (DefaultGestures.Builtin builtin : DefaultGestures.all()) {
            String expected = builtin.name() + RegistrationMedia.extensionFor(builtin.motion());
            boolean shipped = new ClassPathResource(DefaultGestureImages.DIR + expected).exists();
            assertThat(DefaultGestureImages.fileName(builtin.name()))
                    .as("%s (애셋 %s)", builtin.name(), shipped ? "있음" : "없음")
                    .isEqualTo(shipped ? expected : null);
        }
    }

    @Test
    @DisplayName("카탈로그 밖 이름은 애셋을 갖지 않는다 — DB 의 이름으로 클래스패스 경로를 짓지 않는다")
    void onlyCatalogNamesResolve() {
        assertThat(DefaultGestureImages.fileName("손가락 하트")).isNull();
        assertThat(DefaultGestureImages.fileName("../application")).isNull();
        assertThat(DefaultGestureImages.fileName(null)).isNull();
    }
}
