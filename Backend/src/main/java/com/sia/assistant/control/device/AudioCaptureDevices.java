package com.sia.assistant.control.device;

import com.sia.assistant.control.com.ComRef;
import com.sun.jna.Memory;
import com.sun.jna.Pointer;
import com.sun.jna.platform.win32.COM.COMUtils;
import com.sun.jna.platform.win32.Guid;
import com.sun.jna.platform.win32.Ole32;
import com.sun.jna.platform.win32.WTypes;
import com.sun.jna.platform.win32.WinNT;
import com.sun.jna.ptr.IntByReference;
import com.sun.jna.ptr.PointerByReference;
import java.util.ArrayList;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * Core Audio(IMMDeviceEnumerator)로 녹음 장치를 열거한다 — 이름과 <b>엔드포인트 ID</b> 를 함께 낸다.
 * ★ ComWorker 스레드에서만 호출한다. 전 과정 best-effort — 실패하면 빈 목록이다.
 *
 * <p>엔드포인트 ID({@code {0.0.1.00000000}.{guid}})는 이름과 달리 같은 모델을 여러 개 꽂아도 겹치지
 * 않고, 프로세스 밖으로 넘겨도 뜻이 유지된다. 이름만 넘기면 AI 쪽에서 매칭이 깨진다 —
 * PortAudio 의 MME 백엔드는 장치 이름을 31자로 잘라 보고한다.
 *
 * <p>vtable 인덱스는 각 헤더의 선언 순서다 (IUnknown 3개를 포함해 0부터):
 *   IMMDeviceEnumerator.EnumAudioEndpoints=3, GetDefaultAudioEndpoint=4 (mmdeviceapi.h)
 *   IMMDeviceCollection.GetCount=3, Item=4 (mmdeviceapi.h)
 *   IMMDevice.OpenPropertyStore=4, GetId=5 (mmdeviceapi.h)
 *   IPropertyStore.GetValue=5 (propsys.h)
 */
final class AudioCaptureDevices {

    private static final Logger log = LoggerFactory.getLogger(AudioCaptureDevices.class);

    private static final Guid.CLSID CLSID_MM_DEVICE_ENUMERATOR =
            new Guid.CLSID("{BCDE0395-E52F-467C-8E3D-C4579291692E}");
    private static final Guid.IID IID_IMM_DEVICE_ENUMERATOR =
            new Guid.IID("{A95664D2-9614-4F35-A746-DE8DB63617E6}");

    private static final int ENUM_AUDIO_ENDPOINTS = 3;
    private static final int GET_DEFAULT_AUDIO_ENDPOINT = 4;
    private static final int COLLECTION_GET_COUNT = 3;
    private static final int COLLECTION_ITEM = 4;
    private static final int DEVICE_OPEN_PROPERTY_STORE = 4;
    private static final int DEVICE_GET_ID = 5;
    private static final int PROPERTY_STORE_GET_VALUE = 5;

    private static final int E_CAPTURE = 1;          // 녹음(입력) 장치
    private static final int E_CONSOLE = 0;          // 소리 설정이 "기본 장치"로 보여 주는 그 역할
    private static final int DEVICE_STATE_ACTIVE = 1; // 꽂혀 있고 쓸 수 있는 것만
    private static final int STGM_READ = 0;

    /** PKEY_Device_FriendlyName — "마이크(Realtek(R) Audio)" 처럼 사용자가 소리 설정에서 보는 이름. */
    private static final byte[] PKEY_DEVICE_FRIENDLY_NAME_FMTID =
            nativeGuidBytes("{A45C254E-DF1C-4EFD-8020-67D146A850E0}");
    private static final int PKEY_DEVICE_FRIENDLY_NAME_PID = 14;

    /** PROPVARIANT 의 vt=VT_LPWSTR 이면 오프셋 8 에 CoTaskMem 문자열 포인터가 있다. */
    private static final int VT_LPWSTR = 31;
    private static final int PROPVARIANT_SIZE = 24;
    private static final int PROPVARIANT_VALUE_OFFSET = 8;

    private AudioCaptureDevices() {
    }

    /** 활성 녹음 장치 전부. COM 이 없거나 장치가 없으면 빈 목록. */
    static List<CaptureDeviceCatalog.Mic> list() {
        List<CaptureDeviceCatalog.Mic> out = new ArrayList<>();
        ComRef enumerator = null;
        ComRef collection = null;
        try {
            PointerByReference pEnumerator = new PointerByReference();
            WinNT.HRESULT hr = Ole32.INSTANCE.CoCreateInstance(CLSID_MM_DEVICE_ENUMERATOR, null,
                    WTypes.CLSCTX_INPROC_SERVER, IID_IMM_DEVICE_ENUMERATOR, pEnumerator);
            if (COMUtils.FAILED(hr) || pEnumerator.getValue() == null) {
                log.debug("MMDeviceEnumerator 생성 실패: 0x{}", Integer.toHexString(hr.intValue()));
                return out;
            }
            enumerator = new ComRef(pEnumerator.getValue());

            // IMMDeviceEnumerator::EnumAudioEndpoints(eCapture, DEVICE_STATE_ACTIVE, &collection)
            PointerByReference pCollection = new PointerByReference();
            if (ComRef.failed(enumerator.invokeHr(ENUM_AUDIO_ENDPOINTS, E_CAPTURE, DEVICE_STATE_ACTIVE, pCollection))
                    || pCollection.getValue() == null) {
                log.debug("녹음 장치 열거 실패");
                return out;
            }
            collection = new ComRef(pCollection.getValue());

            IntByReference count = new IntByReference();
            if (ComRef.failed(collection.invokeHr(COLLECTION_GET_COUNT, count))) {
                return out;
            }

            String defaultId = defaultCaptureId(enumerator);
            for (int i = 0; i < count.getValue(); i++) {
                PointerByReference pDevice = new PointerByReference();
                if (ComRef.failed(collection.invokeHr(COLLECTION_ITEM, i, pDevice))
                        || pDevice.getValue() == null) {
                    continue;
                }
                ComRef device = new ComRef(pDevice.getValue());
                try {
                    String id = deviceId(device);
                    String name = friendlyName(device);
                    // 이름·ID 어느 쪽이든 못 읽은 장치는 FE 가 고를 수도, AI 가 열 수도 없다
                    if (id != null && name != null) {
                        out.add(new CaptureDeviceCatalog.Mic(name, id, id.equals(defaultId)));
                    }
                } finally {
                    ComRef.release(device);
                }
            }
        } catch (Throwable t) {
            log.warn("마이크 열거 실패: {}", t.toString());
        } finally {
            ComRef.release(collection);
            ComRef.release(enumerator);
        }
        return out;
    }

    /** 기본 입력 장치의 엔드포인트 ID. 마이크가 하나도 없으면 null 이고 isDefault 는 전부 false 가 된다. */
    private static String defaultCaptureId(ComRef enumerator) {
        PointerByReference pDevice = new PointerByReference();
        if (ComRef.failed(enumerator.invokeHr(GET_DEFAULT_AUDIO_ENDPOINT, E_CAPTURE, E_CONSOLE, pDevice))
                || pDevice.getValue() == null) {
            return null;
        }
        ComRef device = new ComRef(pDevice.getValue());
        try {
            return deviceId(device);
        } finally {
            ComRef.release(device);
        }
    }

    /** IMMDevice::GetId — CoTaskMem 문자열이라 읽고 우리가 해제한다. */
    private static String deviceId(ComRef device) {
        PointerByReference pId = new PointerByReference();
        if (ComRef.failed(device.invokeHr(DEVICE_GET_ID, pId)) || pId.getValue() == null) {
            return null;
        }
        Pointer p = pId.getValue();
        try {
            String id = p.getWideString(0);
            return id == null || id.isBlank() ? null : id;
        } finally {
            Ole32.INSTANCE.CoTaskMemFree(p);
        }
    }

    /** 속성 저장소에서 PKEY_Device_FriendlyName 을 읽는다. */
    private static String friendlyName(ComRef device) {
        PointerByReference pStore = new PointerByReference();
        if (ComRef.failed(device.invokeHr(DEVICE_OPEN_PROPERTY_STORE, STGM_READ, pStore))
                || pStore.getValue() == null) {
            return null;
        }
        ComRef store = new ComRef(pStore.getValue());
        try {
            Memory key = friendlyNameKey();
            Memory value = new Memory(PROPVARIANT_SIZE);
            value.clear();
            if (ComRef.failed(store.invokeHr(PROPERTY_STORE_GET_VALUE, key, value))) {
                return null;
            }
            if ((value.getShort(0) & 0xFFFF) != VT_LPWSTR) {
                return null;
            }
            Pointer p = value.getPointer(PROPVARIANT_VALUE_OFFSET);
            if (p == null) {
                return null;
            }
            try {
                String name = p.getWideString(0);
                return name == null || name.isBlank() ? null : name;
            } finally {
                // VT_LPWSTR 의 PropVariantClear 는 이 문자열 하나를 놓아 주는 것과 같다
                Ole32.INSTANCE.CoTaskMemFree(p);
            }
        } finally {
            ComRef.release(store);
        }
    }

    /** PROPERTYKEY = GUID(16) + DWORD pid(4). JNA 에 타입 선언이 없어 직접 만든다. */
    private static Memory friendlyNameKey() {
        Memory key = new Memory(20);
        key.clear();
        key.write(0, PKEY_DEVICE_FRIENDLY_NAME_FMTID, 0, 16);
        key.setInt(16, PKEY_DEVICE_FRIENDLY_NAME_PID);
        return key;
    }

    /**
     * GUID 를 네이티브 배치(Data1·Data2·Data3 리틀엔디안) 16바이트로 뽑는다.
     * ★ {@code Guid.GUID.toByteArray()} 를 쓰면 안 된다 — 그쪽은 문자열에 보이는 순서(빅엔디안)로
     * 담아서, PROPERTYKEY 에 그대로 넣으면 GetValue 가 S_OK 에 vt=VT_EMPTY 를 주며 조용히 실패한다.
     */
    private static byte[] nativeGuidBytes(String guid) {
        Guid.GUID g = new Guid.GUID(guid);
        g.write();
        return g.getPointer().getByteArray(0, 16);
    }
}
