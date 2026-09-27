package com.sia.assistant.settings;

import com.sia.assistant.registration.RegistrationMedia;
import java.util.HashMap;
import java.util.Map;
import org.springframework.core.io.ClassPathResource;
import org.springframework.core.io.Resource;

/**
 * 기본 제공 제스처 9종의 예시 미리보기 — jar 안 {@code seed/gestures/} 에 싣는다.
 *
 * <p>커스텀 제스처의 미리보기는 등록 때 찍은 사용자 보관본(%APPDATA%/SIA/gestures/)이지만 기본 제공은
 * 촬영 단계가 없다. 모양과 표시 문구를 BE 가 소유하므로(DefaultGestures) 그 모양을 보여 주는 그림도 여기 둔다.
 *
 * <p>★디스크로 복사하지 않는다: 전체 삭제가 gestures/ 를 통째로 비우므로
 * (WipeService → GestureService.deleteAllVideos) 복사본은 전체 삭제 한 번에 사라진다. 클래스패스 애셋은
 * 그 경로를 타지 않아 복구 절차도, video_path 컬럼도, 마이그레이션도 필요 없다.
 *
 * <p>파일명은 카탈로그 이름 그대로이고 확장자는 motion 이 정한다(RegistrationMedia) — 정적 7종은 .jpg,
 * 스와이프 2종은 .webm 이다. FE 가 motion 으로 {@code <img>} / {@code <video>} 를 고르기 때문이다.
 * 그래서 확장자를 추정해 둘 다 찾아보지 않는다 — 규칙을 어긴 애셋(동적인데 jpg)은 태그가 어긋난 채
 * 깨져 보이느니 없는 것으로 두는 편이 낫다.
 *
 * <p>애셋이 없으면 조용히 없는 것으로 둔다 — videoUrl 은 null 이고 /video 는 404 다(애셋을 넣기 전과 같다).
 * 그래서 9장을 한꺼번에 준비하지 않아도 되고, 넣은 것부터 목록에 뜬다.
 */
public final class DefaultGestureImages {

    static final String DIR = "seed/gestures/";

    /**
     * 애셋을 가질 수 있는 이름은 기본 제공 카탈로그 9종뿐이다 — DB 의 이름으로 클래스패스 경로를 짓지
     * 않는다는 뜻이기도 하다(커스텀 이름이 {@code ../} 를 담아 다른 리소스를 가리키는 경로를 막는다).
     */
    private static final Map<String, DefaultGestures.Builtin> CATALOG = index();

    private static Map<String, DefaultGestures.Builtin> index() {
        Map<String, DefaultGestures.Builtin> out = new HashMap<>();
        for (DefaultGestures.Builtin builtin : DefaultGestures.all()) {
            out.put(builtin.name(), builtin);
        }
        return Map.copyOf(out);
    }

    /**
     * 이 기본 제공 제스처의 예시 미리보기 파일명. 카탈로그에 없는 이름이거나 애셋이 없으면 null.
     *
     * <p>목록 한 페이지에 스무 번까지 불리지만 결과를 캐시하지 않는다 — 클래스로더 조회라 값싸고,
     * 캐시를 두면 개발 중 애셋을 넣고도 재기동 전까지 안 보이는 쪽이 더 헷갈린다.
     */
    public static String fileName(String name) {
        if (name == null) {
            return null;  // 불변 Map 은 null 키 조회에 NPE 를 던진다
        }
        DefaultGestures.Builtin builtin = CATALOG.get(name);
        if (builtin == null) {
            return null;
        }
        String file = builtin.name() + RegistrationMedia.extensionFor(builtin.motion());
        return new ClassPathResource(DIR + file).exists() ? file : null;
    }

    /** {@link #fileName(String)} 이 돌려준 이름의 원본. */
    public static Resource resource(String fileName) {
        return new ClassPathResource(DIR + fileName);
    }

    private DefaultGestureImages() {
    }
}
