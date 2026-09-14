package com.sia.assistant.control.audio;

import com.sun.jna.Pointer;
import com.sun.jna.platform.win32.COM.COMUtils;
import com.sun.jna.platform.win32.COM.Unknown;
import com.sun.jna.platform.win32.Guid;
import com.sun.jna.platform.win32.Ole32;
import com.sun.jna.platform.win32.WTypes;
import com.sun.jna.platform.win32.WinNT;
import com.sun.jna.ptr.FloatByReference;
import com.sun.jna.ptr.IntByReference;
import com.sun.jna.ptr.PointerByReference;
import java.util.function.Function;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Core Audio(IAudioEndpointVolume)로 기본 재생 장치의 마스터 볼륨을 읽고 쓴다 — 단계가 아니라 절대값이다.
 * 미디어 키(VK_VOLUME_UP/DOWN)로는 현재 값을 알 수도, 목표 값에 맞출 수도 없다.
 * ★ ComWorker 스레드에서만 호출한다. 전 과정 best-effort — 실패하면 null 이고 AudioService 가 환원한다.
 *
 * <p>스칼라(0.0~1.0)는 작업표시줄 볼륨 슬라이더와 같은 척도다 — 30 으로 맞추면 슬라이더도 30% 에 선다.
 * 엔드포인트는 호출마다 새로 얻는다: 기본 장치는 헤드셋 연결 등으로 도중에 바뀌고, 캐시한 포인터는 그때 죽는다.
 *
 * <p>vtable 인덱스는 각 헤더의 선언 순서다:
 *   IMMDeviceEnumerator.GetDefaultAudioEndpoint=4 (mmdeviceapi.h)
 *   IMMDevice.Activate=3 (mmdeviceapi.h)
 *   IAudioEndpointVolume.SetMasterVolumeLevelScalar=7, GetMasterVolumeLevelScalar=9,
 *     SetMute=14, GetMute=15 (endpointvolume.h)
 */
final class EndpointVolume {

    private static final Logger log = LoggerFactory.getLogger(EndpointVolume.class);

    private static final Guid.CLSID CLSID_MM_DEVICE_ENUMERATOR =
            new Guid.CLSID("{BCDE0395-E52F-467C-8E3D-C4579291692E}");
    private static final Guid.IID IID_IMM_DEVICE_ENUMERATOR =
            new Guid.IID("{A95664D2-9614-4F35-A746-DE8DB63617E6}");
    private static final Guid.IID IID_IAUDIO_ENDPOINT_VOLUME =
            new Guid.IID("{5CDF2C82-841E-4546-9722-0CF74078229A}");

    private static final int GET_DEFAULT_AUDIO_ENDPOINT = 4;
    private static final int ACTIVATE = 3;
    private static final int SET_MASTER_VOLUME_LEVEL_SCALAR = 7;
    private static final int GET_MASTER_VOLUME_LEVEL_SCALAR = 9;
    private static final int SET_MUTE = 14;
    private static final int GET_MUTE = 15;

    private static final int E_RENDER = 0;     // 재생(출력) 장치
    private static final int E_MULTIMEDIA = 1; // 음악·영상 역할 — 사용자가 슬라이더로 만지는 그 장치

    /** level 은 0~100 퍼센트. */
    record State(int level, boolean muted) {
    }

    private EndpointVolume() {
    }

    /** 현재 볼륨. 실패하면 null. */
    static State read() {
        return onEndpoint(EndpointVolume::stateOf);
    }

    /**
     * level(0~100)로 맞추고 실제 반영된 값을 돌려준다. 실패하면 null.
     * level 이 0 보다 크면 음소거도 함께 푼다 — 볼륨을 먼저 낮춘 뒤에 풀어야 옛 볼륨으로 한 번 터지지 않는다.
     */
    static State apply(int level) {
        return onEndpoint(volume -> {
            // 세 번째 인자는 LPCGUID pguidEventContext — 변경 알림을 우리 것으로 표시할 때만 쓴다
            if (failed(volume.invokeHr(SET_MASTER_VOLUME_LEVEL_SCALAR, Float.valueOf(level / 100f), null))) {
                return null;
            }
            // SetMute 는 상태가 안 바뀌면 S_FALSE(=1)를 준다 — 성공 쪽이라 FAILED 판정에 걸리지 않는다
            if (level > 0 && failed(volume.invokeHr(SET_MUTE, 0, null))) {
                return null;
            }
            return stateOf(volume);
        });
    }

    private static State stateOf(Com volume) {
        FloatByReference scalar = new FloatByReference();
        IntByReference muted = new IntByReference();
        if (failed(volume.invokeHr(GET_MASTER_VOLUME_LEVEL_SCALAR, scalar))
                || failed(volume.invokeHr(GET_MUTE, muted))) {
            return null;
        }
        return new State(percent(scalar.getValue()), muted.getValue() != 0);
    }

    /** IAudioEndpointVolume 을 얻어 body 를 돌리고 역순으로 해제한다. */
    private static State onEndpoint(Function<Com, State> body) {
        Com enumerator = null;
        Com device = null;
        Com volume = null;
        try {
            PointerByReference pEnumerator = new PointerByReference();
            WinNT.HRESULT hr = Ole32.INSTANCE.CoCreateInstance(CLSID_MM_DEVICE_ENUMERATOR, null,
                    WTypes.CLSCTX_INPROC_SERVER, IID_IMM_DEVICE_ENUMERATOR, pEnumerator);
            if (COMUtils.FAILED(hr) || pEnumerator.getValue() == null) {
                log.debug("MMDeviceEnumerator 생성 실패: 0x{}", Integer.toHexString(hr.intValue()));
                return null;
            }
            enumerator = new Com(pEnumerator.getValue());

            // IMMDeviceEnumerator::GetDefaultAudioEndpoint(eRender, eMultimedia, &device)
            PointerByReference pDevice = new PointerByReference();
            if (failed(enumerator.invokeHr(GET_DEFAULT_AUDIO_ENDPOINT, E_RENDER, E_MULTIMEDIA, pDevice))
                    || pDevice.getValue() == null) {
                log.debug("기본 재생 장치가 없습니다 — 출력 장치 미연결");
                return null;
            }
            device = new Com(pDevice.getValue());

            // IMMDevice::Activate(IID_IAudioEndpointVolume, CLSCTX_INPROC_SERVER, NULL, &volume)
            PointerByReference pVolume = new PointerByReference();
            if (failed(device.invokeHr(ACTIVATE, IID_IAUDIO_ENDPOINT_VOLUME,
                    WTypes.CLSCTX_INPROC_SERVER, null, pVolume)) || pVolume.getValue() == null) {
                log.debug("IAudioEndpointVolume 활성화 실패");
                return null;
            }
            volume = new Com(pVolume.getValue());

            return body.apply(volume);
        } catch (Throwable t) {
            log.warn("볼륨 엔드포인트 접근 실패: {}", t.toString());
            return null;
        } finally {
            release(volume);
            release(device);
            release(enumerator);
        }
    }

    /** 스칼라(0.0~1.0) → 퍼센트. 장치가 경계를 살짝 넘겨 주더라도 0~100 밖으로는 나가지 않는다. */
    private static int percent(float scalar) {
        return Math.max(0, Math.min(100, Math.round(scalar * 100f)));
    }

    private static boolean failed(int hr) {
        return COMUtils.FAILED(new WinNT.HRESULT(hr));
    }

    private static void release(Unknown u) {
        if (u != null) {
            try {
                u.Release();
            } catch (Throwable ignored) {
            }
        }
    }

    /** vtable 직접 호출용 래퍼 — 첫 인자로 인터페이스 포인터를 넣는 규약을 감춘다. */
    private static final class Com extends Unknown {
        Com(Pointer pointer) {
            super(pointer);
        }

        int invokeHr(int vtableId, Object... args) {
            Object[] full = new Object[args.length + 1];
            full[0] = getPointer();
            System.arraycopy(args, 0, full, 1, args.length);
            return _invokeNativeInt(vtableId, full);
        }
    }
}
