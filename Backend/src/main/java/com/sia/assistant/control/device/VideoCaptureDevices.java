package com.sia.assistant.control.device;

import com.sun.jna.Memory;
import com.sun.jna.Native;
import com.sun.jna.platform.win32.Guid;
import com.sun.jna.platform.win32.Kernel32;
import com.sun.jna.platform.win32.SetupApi;
import com.sun.jna.platform.win32.WinBase;
import com.sun.jna.platform.win32.WinError;
import com.sun.jna.platform.win32.WinNT;
import com.sun.jna.ptr.IntByReference;
import java.util.ArrayList;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * SetupAPI 로 카메라를 열거한다 — 이름과 <b>장치 인터페이스 경로</b>를 함께 낸다.
 *
 * <p>DirectShow(ICreateDevEnum → IEnumMoniker → IPropertyBag)로도 같은 목록을 얻지만 COM vtable 을
 * 세 겹 타면서 VARIANT 마샬링까지 얹힌다. SetupAPI 는 플랫 C API 라 아파트 규칙도, vtable 인덱스
 * 추측도 없다 — 그래서 이 경로를 골랐다(확정 2026-09-09).
 *
 * <p>인터페이스 클래스는 KSCATEGORY_VIDEO_CAMERA 다. 여기서 나오는 경로는 Media Foundation 의
 * 심볼릭 링크와 <b>같은 문자열</b>이라, OpenCV 가 Windows 기본으로 쓰는 MSMF 백엔드에서 그대로
 * 맞는다. DirectShow 의 DevicePath 는 끝의 카테고리 GUID 만 다르므로, DShow 로 여는 쪽은
 * 카테고리 GUID 앞의 장치 인스턴스 부분까지만 비교해야 한다.
 *
 * <p>전 과정 best-effort — 실패하면 빈 목록이다.
 */
final class VideoCaptureDevices {

    private static final Logger log = LoggerFactory.getLogger(VideoCaptureDevices.class);

    /** KSCATEGORY_VIDEO_CAMERA (ks.h) — 웹캠·내장 카메라가 등록하는 인터페이스 클래스. */
    private static final Guid.GUID KSCATEGORY_VIDEO_CAMERA =
            new Guid.GUID("{E5323777-F976-4F5B-9B55-B94699C46E44}");

    private static final int SPDRP_DEVICEDESC = 0x00000000;
    private static final int SPDRP_FRIENDLYNAME = 0x0000000C;

    /**
     * SP_DEVICE_INTERFACE_DETAIL_DATA_W = {DWORD cbSize; WCHAR DevicePath[1];}.
     * cbSize 는 구조체 크기를 그대로 요구한다 — 64비트는 정렬 때문에 8, 32비트는 6 이다.
     * 이 값이 틀리면 ERROR_INVALID_USER_BUFFER 로 조용히 실패한다.
     */
    private static final int DETAIL_CB_SIZE = Native.POINTER_SIZE == 8 ? 8 : 6;
    private static final int DETAIL_PATH_OFFSET = 4;

    private VideoCaptureDevices() {
    }

    /** 꽂혀 있는 카메라 전부. 드라이버가 없거나 장치가 없으면 빈 목록. */
    static List<CaptureDeviceCatalog.Camera> list() {
        List<CaptureDeviceCatalog.Camera> out = new ArrayList<>();
        WinNT.HANDLE set = null;
        try {
            set = SetupApi.INSTANCE.SetupDiGetClassDevs(KSCATEGORY_VIDEO_CAMERA, null, null,
                    SetupApi.DIGCF_PRESENT | SetupApi.DIGCF_DEVICEINTERFACE);
            if (set == null || WinBase.INVALID_HANDLE_VALUE.equals(set)) {
                log.debug("카메라 장치 집합을 열지 못했습니다: {}", Kernel32.INSTANCE.GetLastError());
                return out;
            }
            for (int i = 0; ; i++) {
                SetupApi.SP_DEVICE_INTERFACE_DATA ifData = new SetupApi.SP_DEVICE_INTERFACE_DATA();
                ifData.cbSize = ifData.size();
                if (!SetupApi.INSTANCE.SetupDiEnumDeviceInterfaces(set, null, KSCATEGORY_VIDEO_CAMERA, i, ifData)) {
                    int err = Kernel32.INSTANCE.GetLastError();
                    if (err != WinError.ERROR_NO_MORE_ITEMS) {
                        log.debug("카메라 인터페이스 {}번 열거 실패: {}", i, err);
                    }
                    break;
                }
                CaptureDeviceCatalog.Camera camera = read(set, ifData);
                if (camera != null) {
                    out.add(camera);
                }
            }
        } catch (Throwable t) {
            log.warn("카메라 열거 실패: {}", t.toString());
        } finally {
            if (set != null && !WinBase.INVALID_HANDLE_VALUE.equals(set)) {
                SetupApi.INSTANCE.SetupDiDestroyDeviceInfoList(set);
            }
        }
        return out;
    }

    /** 인터페이스 하나에서 경로와 이름을 읽는다. 경로를 못 읽으면 null — AI 가 열 수 없는 장치다. */
    private static CaptureDeviceCatalog.Camera read(WinNT.HANDLE set,
                                                    SetupApi.SP_DEVICE_INTERFACE_DATA ifData) {
        // 1차 호출은 크기만 묻는다 (ERROR_INSUFFICIENT_BUFFER 로 실패하는 것이 정상)
        IntByReference required = new IntByReference();
        SetupApi.INSTANCE.SetupDiGetDeviceInterfaceDetail(set, ifData, null, 0, required, null);
        if (required.getValue() <= DETAIL_PATH_OFFSET) {
            return null;
        }
        Memory detail = new Memory(required.getValue());
        detail.clear();
        detail.setInt(0, DETAIL_CB_SIZE);
        SetupApi.SP_DEVINFO_DATA devInfo = new SetupApi.SP_DEVINFO_DATA();
        devInfo.cbSize = devInfo.size();
        if (!SetupApi.INSTANCE.SetupDiGetDeviceInterfaceDetail(
                set, ifData, detail, required.getValue(), null, devInfo)) {
            log.debug("카메라 인터페이스 경로 조회 실패: {}", Kernel32.INSTANCE.GetLastError());
            return null;
        }
        String path = detail.getWideString(DETAIL_PATH_OFFSET);
        if (path == null || path.isBlank()) {
            return null;
        }
        // FriendlyName 을 두지 않는 드라이버가 있어 DeviceDesc 로 물러난다. 둘 다 없으면 경로를 보여 준다
        String name = property(set, devInfo, SPDRP_FRIENDLYNAME);
        if (name == null) {
            name = property(set, devInfo, SPDRP_DEVICEDESC);
        }
        return new CaptureDeviceCatalog.Camera(name == null ? path : name, path);
    }

    /** 장치 등록정보 문자열 하나. 없으면 null. */
    private static String property(WinNT.HANDLE set, SetupApi.SP_DEVINFO_DATA devInfo, int property) {
        IntByReference size = new IntByReference();
        SetupApi.INSTANCE.SetupDiGetDeviceRegistryProperty(set, devInfo, property, null, null, 0, size);
        if (size.getValue() <= 0) {
            return null;
        }
        Memory buffer = new Memory(size.getValue());
        buffer.clear();
        if (!SetupApi.INSTANCE.SetupDiGetDeviceRegistryProperty(
                set, devInfo, property, null, buffer, (int) buffer.size(), null)) {
            return null;
        }
        String value = buffer.getWideString(0);
        return value == null || value.isBlank() ? null : value;
    }
}
