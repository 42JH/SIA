package com.sia.assistant.control.audio;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.control.com.ComWorker;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * volume.set 의 실체이자 context.get 의 volume 필드 공급자.
 * COM 호출이라 아무 요청 스레드에서나 부를 수 없다 — 전부 ComWorker 스레드로 넘긴다.
 */
@Service
public class AudioService {

    private static final Logger log = LoggerFactory.getLogger(AudioService.class);

    /** 로컬 오디오 엔드포인트 호출이라 빠르다 — 이보다 오래 걸리면 장치 쪽이 막힌 것이다. */
    private static final long TIMEOUT_MS = 3000;

    private final ComWorker comWorker;

    public AudioService(ComWorker comWorker) {
        this.comWorker = comWorker;
    }

    /** level 은 0~100 퍼센트, muted 는 시스템 음소거 상태. */
    public record Volume(int level, boolean muted) {
    }

    /**
     * 시스템 볼륨을 정확한 값으로 맞추고 실제 반영된 값을 돌려준다.
     * 범위 밖은 잘라서 맞춘다 — "최대로"가 150 으로 와도 실패가 아니라 100 이다.
     */
    public Volume set(int level) {
        int target = Math.max(0, Math.min(100, level));
        EndpointVolume.State state = comWorker.call("볼륨 설정", TIMEOUT_MS, () -> EndpointVolume.apply(target));
        if (state == null) {
            throw new ApiException(ErrorCode.INTERNAL_ERROR, "시스템 볼륨을 조절하지 못했습니다");
        }
        return new Volume(state.level(), state.muted());
    }

    /** 현재 볼륨. 실패하면 null — context.get 은 볼륨 없이도 성립하므로 예외를 밖으로 내지 않는다. */
    public Volume currentOrNull() {
        try {
            EndpointVolume.State state = comWorker.call("볼륨 조회", TIMEOUT_MS, EndpointVolume::read);
            return state == null ? null : new Volume(state.level(), state.muted());
        } catch (RuntimeException e) {
            log.debug("현재 볼륨 조회 실패 — 볼륨 없이 컨텍스트를 만든다: {}", e.toString());
            return null;
        }
    }
}
