package com.sia.assistant.control.com;

import com.sun.jna.platform.win32.COM.COMLateBindingObject;
import com.sun.jna.platform.win32.COM.IDispatch;
import com.sun.jna.platform.win32.OleAuto;
import com.sun.jna.platform.win32.Variant;
import com.sun.jna.platform.win32.WTypes;
import com.sun.jna.platform.win32.WinDef;

/**
 * IDispatch 레이트 바인딩 헬퍼 — Shell.Application / WScript.Shell 자동화용.
 * ★ 반드시 ComWorker 스레드 안에서만 생성·사용한다 (COM 아파트 규칙).
 * dispatch 값을 반환하는 프로퍼티/메서드는 새 LateDispatch 로 소유권을 넘기므로 try-with-resources 로 닫는다.
 */
public final class LateDispatch extends COMLateBindingObject implements AutoCloseable {

    public LateDispatch(String progId) {
        super(progId, false);
    }

    private LateDispatch(IDispatch dispatch) {
        super(dispatch);
    }

    // ------------------------------------------------------------ 프로퍼티

    public String strProp(String name) {
        Variant.VARIANT v = rawProp(name);
        try {
            return asString(v);
        } finally {
            clear(v);
        }
    }

    public long longProp(String name) {
        Variant.VARIANT v = rawProp(name);
        try {
            return asLong(v);
        } finally {
            clear(v);
        }
    }

    public int intProp(String name) {
        return (int) longProp(name);
    }

    /** dispatch 프로퍼티. 값이 비어 있으면 null. 반환된 객체는 호출자가 close() 한다. */
    public LateDispatch dispProp(String name) {
        return wrap(rawProp(name));
    }

    // ------------------------------------------------------------ 메서드

    public LateDispatch dispCall(String name, Variant.VARIANT... args) {
        return wrap(rawCall(name, args));
    }

    public String strCall(String name, Variant.VARIANT... args) {
        Variant.VARIANT v = rawCall(name, args);
        try {
            return asString(v);
        } finally {
            clear(v);
        }
    }

    // ------------------------------------------------------------ IDispatch 원호출

    private Variant.VARIANT rawProp(String name) {
        Variant.VARIANT.ByReference result = new Variant.VARIANT.ByReference();
        oleMethod(OleAuto.DISPATCH_PROPERTYGET, result, getIDispatch(), name);
        return result;
    }

    private Variant.VARIANT rawCall(String name, Variant.VARIANT... args) {
        Variant.VARIANT.ByReference result = new Variant.VARIANT.ByReference();
        if (args == null || args.length == 0) {
            oleMethod(OleAuto.DISPATCH_METHOD, result, getIDispatch(), name);
        } else {
            oleMethod(OleAuto.DISPATCH_METHOD, result, getIDispatch(), name, args);
        }
        return result;
    }

    // ------------------------------------------------------------ VARIANT 유틸

    public static Variant.VARIANT intVariant(int value) {
        Variant.VARIANT v = new Variant.VARIANT();
        v.setValue(Variant.VT_I4, new WinDef.LONG(value));
        return v;
    }

    /** 문자열 VARIANT — 사용 후 clear() 로 BSTR 을 해제해야 한다. */
    public static Variant.VARIANT strVariant(String value) {
        Variant.VARIANT v = new Variant.VARIANT();
        v.setValue(Variant.VT_BSTR, OleAuto.INSTANCE.SysAllocString(value));
        return v;
    }

    public static void clear(Variant.VARIANT v) {
        if (v != null) {
            try {
                OleAuto.INSTANCE.VariantClear(v);
            } catch (Throwable ignored) {
                // 해제 실패는 무시 — 로컬 수명 짧은 프로세스에서 치명적이지 않다
            }
        }
    }

    private LateDispatch wrap(Variant.VARIANT v) {
        if (v == null) {
            return null;
        }
        Object value = v.getValue();
        if (value instanceof IDispatch d) {
            // 소유권 이전 — VariantClear 하지 않는다 (하면 Release 되어 래퍼가 죽은 포인터를 든다)
            return new LateDispatch(d);
        }
        clear(v);
        return null;
    }

    private static String asString(Variant.VARIANT v) {
        if (v == null) {
            return null;
        }
        Object value = v.getValue();
        if (value == null) {
            return null;
        }
        if (value instanceof WTypes.BSTR b) {
            return b.getValue();
        }
        return String.valueOf(value);
    }

    private static long asLong(Variant.VARIANT v) {
        if (v == null) {
            return 0L;
        }
        Object value = v.getValue();
        if (value instanceof Number n) {
            return n.longValue();
        }
        return 0L;
    }

    @Override
    public void close() {
        release();
    }
}
