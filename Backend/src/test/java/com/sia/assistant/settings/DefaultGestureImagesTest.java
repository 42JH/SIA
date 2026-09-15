package com.sia.assistant.settings;

import static org.assertj.core.api.Assertions.assertThat;
import static org.junit.jupiter.api.Assumptions.assumeTrue;

import com.sia.assistant.registration.RegistrationMedia;
import java.nio.file.Files;
import java.util.Set;
import java.util.stream.Collectors;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.core.io.ClassPathResource;

/**
 * 기본 제공 제스처의 예시 애셋 조회 — 배포에 실린 seed/gestures/ 의 실물을 그대로 본다.
 * 카탈로그 이름과 파일 이름이 한 글자라도 어긋나면 그 제스처의 미리보기가 조용히 빈칸이 되므로,
 * 둘이 맞는지는 실행 중에 드러나지 않는다. 그 대조가 이 테스트다.
 */
class DefaultGestureImagesTest {

    @Test
    @DisplayName("9종 전부 애셋이 실려 있다 — 이름이 어긋나면 그 제스처만 조용히 빈칸이 된다")
    void allNineAreShipped() {
        for (DefaultGestures.Builtin builtin : DefaultGestures.all()) {
            assertThat(DefaultGestureImages.fileName(builtin.name()))
                    .as("%s 의 예시 애셋", builtin.name())
                    .isEqualTo(builtin.name() + RegistrationMedia.extensionFor(builtin.motion()));
        }
    }

    @Test
    @DisplayName("애셋 파일명은 대소문자까지 카탈로그와 같다 — Windows 는 대소문자를 가리지 않아 jar 로 묶은 뒤에야 깨진다")
    void namesMatchCaseExactly() throws Exception {
        // ClassPathResource.exists() 는 풀린 클래스패스에서 파일 시스템 규칙을 따라간다: Windows 에서는
        // victory.jpg 라도 Victory.jpg 조회가 성공한다. jar 안에서는 항목 이름이 정확히 일치해야 하므로
        // 대소문자가 어긋난 애셋은 개발 중엔 멀쩡하다가 배포본에서만 빈칸이 된다. 여기서 실제 이름을 본다.
        ClassPathResource dir = new ClassPathResource(DefaultGestureImages.DIR);
        assumeTrue(dir.isFile(), "탐색 가능한 클래스패스에서만 검사한다");
        Set<String> onDisk;
        try (var entries = Files.list(dir.getFile().toPath())) {
            onDisk = entries.map(path -> path.getFileName().toString()).collect(Collectors.toSet());
        }
        for (DefaultGestures.Builtin builtin : DefaultGestures.all()) {
            assertThat(onDisk).as("%s 의 애셋 파일명", builtin.name())
                    .contains(builtin.name() + RegistrationMedia.extensionFor(builtin.motion()));
        }
    }

    @Test
    @DisplayName("정적은 jpg, 동적 스와이프는 webm — FE 가 motion 으로 <img>/<video> 를 고르기 때문")
    void extensionFollowsMotion() {
        assertThat(DefaultGestureImages.fileName("Open_Palm")).isEqualTo("Open_Palm.jpg");
        assertThat(DefaultGestureImages.fileName("Swipe_Left")).isEqualTo("Swipe_Left.webm");
    }

    @Test
    @DisplayName("카탈로그 밖 이름은 애셋을 갖지 않는다 — DB 의 이름으로 클래스패스 경로를 짓지 않는다")
    void onlyCatalogNamesResolve() {
        assertThat(DefaultGestureImages.fileName("손가락 하트")).isNull();
        assertThat(DefaultGestureImages.fileName("../application")).isNull();
        assertThat(DefaultGestureImages.fileName(null)).isNull();
    }
}
