package com.sia.assistant.control.device;

import com.sia.assistant.control.com.ComWorker;
import java.util.List;
import org.springframework.stereotype.Service;

/**
 * 초기설정 화면이 고르는 입력 장치 목록 — {@code GET /api/devices} 의 본문을 만든다.
 *
 * <p>열거 주체를 BE 로 둔 이유(확정 2026-09-09)는 <b>식별자</b>다. FE 가 렌더러에서
 * {@code navigator.mediaDevices.enumerateDevices()} 로 열거하면 권한을 받기 전 {@code label} 이 빈
 * 문자열이고, {@code deviceId} 는 오리진별 해시라 별 프로세스인 AI 가 그 값으로 장치를 열 수 없다.
 * OS 레벨에서 열거하면 프로세스 간에 통하는 식별자를 줄 수 있다.
 *
 * <p>사용자가 고른 값은 설정의 {@code micDevice}/{@code micDeviceId} ·
 * {@code cameraDevice}/{@code cameraDeviceId} 로 저장되고, 저장 성공 시 BE 가 AI 에
 * {@code settings_changed} 로 그대로 실어 보낸다 — 이 클래스는 목록만 만들고 통지에는 관여하지 않는다.
 *
 * <p>전 과정 best-effort 다. 열거에 실패하면 예외 대신 빈 목록이다 — 초기설정을 500 으로 막는 것보다
 * 낫다. 마이크는 "시스템 기본"으로 진행할 수 있고, 카메라는 고를 것이 없다는 뜻이 된다.
 */
@Service
public class CaptureDeviceCatalog {

    /**
     * 마이크 하나.
     *
     * @param name     OS 가 보고하는 장치 이름 원문 (설정 {@code micDevice} 로 저장된다).
     *                 같은 모델을 두 개 꽂으면 이름이 겹칠 수 있다 — 구분은 id 로 한다
     * @param id       Core Audio 엔드포인트 ID (설정 {@code micDeviceId} 로 저장된다)
     * @param isDefault Windows 소리 설정의 기본 입력 장치(eConsole)인지
     */
    public record Mic(String name, String id, boolean isDefault) {
    }

    /**
     * 카메라 하나. {@code isDefault} 가 없는 것은 <b>OS 에 기본 카메라가 없기 때문</b>이다 —
     * 마이크의 {@code isDefault} 는 Core Audio 에 물어본 답이지만 카메라에는 물어볼 API 가 없고,
     * 넣으려면 BE 가 임의로 정해야 해서 이름이 거짓이 된다. 고르지 않으면 설정이 {@code null} 이고
     * 그때는 AI 가 열거 순서 첫 장치를 연다.
     *
     * @param name OS 가 보고하는 장치 이름 원문 (설정 {@code cameraDevice} 로 저장된다)
     * @param id   장치 인터페이스 경로 (설정 {@code cameraDeviceId} 로 저장된다)
     */
    public record Camera(String name, String id) {
    }

    /** 장치 열거는 밀리초 단위로 끝난다 — 이보다 오래 걸리면 드라이버가 걸린 것이다. */
    private static final long TIMEOUT_MS = 3000;

    private final ComWorker comWorker;

    public CaptureDeviceCatalog(ComWorker comWorker) {
        this.comWorker = comWorker;
    }

    /** 연결·활성 상태인 마이크 전부. Core Audio 는 COM 이라 com-worker 스레드에서 돈다. */
    public List<Mic> mics() {
        return comWorker.call("마이크 목록 조회", TIMEOUT_MS, AudioCaptureDevices::list);
    }

    /** 연결된 카메라 전부. SetupAPI 는 플랫 C API 라 COM 아파트와 무관하다. */
    public List<Camera> cameras() {
        return VideoCaptureDevices.list();
    }
}
