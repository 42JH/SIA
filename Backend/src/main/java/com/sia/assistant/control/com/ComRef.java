package com.sia.assistant.control.com;

import com.sun.jna.Pointer;
import com.sun.jna.platform.win32.COM.COMUtils;
import com.sun.jna.platform.win32.COM.Unknown;
import com.sun.jna.platform.win32.WinNT;

/**
 * vtable 을 직접 부르는 COM 인터페이스 포인터 래퍼 — 첫 인자로 자기 포인터를 넣는 규약을 감춘다.
 * JNA 에 타입 선언이 없는 인터페이스(IUIAutomation 계열)를 부를 때 쓴다.
 * ★ ComWorker 스레드에서만 쓴다. 아파트 규칙 때문에 다른 스레드에서 부르면 안 된다.
 */
public final class ComRef extends Unknown {

    public ComRef(Pointer pointer) {
        super(pointer);
    }

    /** vtableId 는 해당 헤더의 선언 순서다 (IUnknown 3개를 포함해 0부터 센다). */
    public int invokeHr(int vtableId, Object... args) {
        Object[] full = new Object[args.length + 1];
        full[0] = getPointer();
        System.arraycopy(args, 0, full, 1, args.length);
        return _invokeNativeInt(vtableId, full);
    }

    public static boolean failed(int hr) {
        return COMUtils.FAILED(new WinNT.HRESULT(hr));
    }

    /** null 안전 Release — 정리 경로에서 예외가 새지 않게 한다. */
    public static void release(Unknown u) {
        if (u != null) {
            try {
                u.Release();
            } catch (Throwable ignored) {
                // 이미 죽은 인터페이스 포인터 — 정리 중이므로 무시한다
            }
        }
    }
}
