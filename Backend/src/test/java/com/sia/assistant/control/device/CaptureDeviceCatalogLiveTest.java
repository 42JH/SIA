package com.sia.assistant.control.device;

import static org.assertj.core.api.Assertions.assertThat;

import com.sia.assistant.control.com.ComWorker;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;

/**
 * 실제 장치를 대상으로 도는 스모크 테스트 — Core Audio vtable 인덱스와 SetupAPI 구조체 크기가
 * 맞는지는 이것으로만 확인된다 (컴파일은 둘 다 틀려도 통과하고, 틀리면 조용히 빈 목록이 된다).
 *
 * <p>마이크·카메라가 꽂힌 사용자 세션이 필요해 CI 에서는 돌 수 없다. 기본은 비활성이고
 * {@code ./gradlew test -Dsia.live.devices=true --tests '*CaptureDeviceCatalogLiveTest'} 로만 켠다.
 */
@EnabledIfSystemProperty(named = "sia.live.devices", matches = "true")
class CaptureDeviceCatalogLiveTest {

    @Test
    @DisplayName("마이크를 이름과 엔드포인트 ID 로 열거한다 — 기본 장치가 정확히 하나 표시된다")
    void enumeratesMics() {
        CaptureDeviceCatalog catalog = new CaptureDeviceCatalog(new ComWorker());

        List<CaptureDeviceCatalog.Mic> mics = catalog.mics();

        mics.forEach(m -> System.out.printf("mic  default=%-5s %s%n      id=%s%n",
                m.isDefault(), m.name(), m.id()));
        assertThat(mics)
                .withFailMessage("마이크를 꽂은 뒤 다시 실행하세요 — 빈 목록이면 vtable 인덱스도 의심하세요")
                .isNotEmpty();
        assertThat(mics).allSatisfy(m -> {
            assertThat(m.name()).isNotBlank();
            // 엔드포인트 ID 는 {0.0.1.00000000}.{guid} 형태다 — 이름과 달리 장치마다 유일하다
            assertThat(m.id()).startsWith("{0.0.1.");
        });
        assertThat(mics).extracting(CaptureDeviceCatalog.Mic::id).doesNotHaveDuplicates();
        assertThat(mics.stream().filter(CaptureDeviceCatalog.Mic::isDefault)).hasSize(1);
    }

    @Test
    @DisplayName("카메라를 이름과 장치 인터페이스 경로로 열거한다")
    void enumeratesCameras() {
        CaptureDeviceCatalog catalog = new CaptureDeviceCatalog(new ComWorker());

        List<CaptureDeviceCatalog.Camera> cameras = catalog.cameras();

        cameras.forEach(c -> System.out.printf("cam  %s%n      id=%s%n", c.name(), c.id()));
        assertThat(cameras)
                .withFailMessage("카메라를 꽂은 뒤 다시 실행하세요 — 빈 목록이면 DETAIL_CB_SIZE 도 의심하세요")
                .isNotEmpty();
        assertThat(cameras).allSatisfy(c -> {
            assertThat(c.name()).isNotBlank();
            // 심볼릭 링크는 \\?\ 로 시작하고 끝에 인터페이스 클래스 GUID 가 붙는다
            assertThat(c.id()).startsWith("\\\\?\\");
        });
        assertThat(cameras).extracting(CaptureDeviceCatalog.Camera::id).doesNotHaveDuplicates();
    }
}
