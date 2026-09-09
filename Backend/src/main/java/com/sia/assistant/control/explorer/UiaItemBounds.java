package com.sia.assistant.control.explorer;

import com.sun.jna.Pointer;
import com.sun.jna.Structure;
import com.sun.jna.platform.win32.COM.COMUtils;
import com.sun.jna.platform.win32.COM.Unknown;
import com.sun.jna.platform.win32.Guid;
import com.sun.jna.platform.win32.OaIdl;
import com.sun.jna.platform.win32.OaIdlUtil;
import com.sun.jna.platform.win32.Ole32;
import com.sun.jna.platform.win32.Variant;
import com.sun.jna.platform.win32.WTypes;
import com.sun.jna.platform.win32.WinDef;
import com.sun.jna.platform.win32.WinNT;
import com.sun.jna.ptr.IntByReference;
import com.sun.jna.ptr.PointerByReference;
import java.util.HashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * UIA(UI Automation)로 탐색기 창의 리스트 항목 화면 좌표를 얻는다 — 표시 이름 → 사각형.
 * Win10/11 탐색기의 항목 뷰는 DirectUI 라 ListView 메시지로는 좌표를 못 얻고 UIA 가 유일한 통로다.
 * ★ ComWorker 스레드에서만 호출한다. 전 과정 best-effort — 실패하면 빈 맵 (bounds 없이도 도구는 성립).
 *
 * vtable 인덱스는 UIAutomationClient.h 선언 순서다:
 *   IUIAutomation.ElementFromHandle=6, CreateTrueCondition=21, CreatePropertyCondition=23
 *   IUIAutomationElement.FindAll=6, GetCurrentPropertyValue=10
 *   IUIAutomationElementArray.get_Length=3, GetElement=4
 */
final class UiaItemBounds {

    private static final Logger log = LoggerFactory.getLogger(UiaItemBounds.class);

    private static final Guid.CLSID CLSID_CUIAUTOMATION =
            new Guid.CLSID("{FF48DBA4-60EF-4201-AA87-54103EEF594E}");
    private static final Guid.IID IID_IUIAUTOMATION =
            new Guid.IID("{30CBE57D-D9D0-452A-AB13-7AC5AC4825EE}");

    private static final int TREE_SCOPE_DESCENDANTS = 4;
    private static final int UIA_BOUNDING_RECTANGLE_PROPERTY = 30001;
    private static final int UIA_CONTROL_TYPE_PROPERTY = 30003;
    private static final int UIA_NAME_PROPERTY = 30005;
    private static final int UIA_LIST_ITEM_CONTROL_TYPE = 50007;
    private static final int MAX_ITEMS = 512;

    record Rect(int x, int y, int w, int h) {
    }

    private UiaItemBounds() {
    }

    /** 표시 이름 → 화면 사각형. 이름이 중복이면(확장자 숨김 충돌) 그 이름은 제외한다. */
    static Map<String, Rect> byName(long hwnd) {
        Map<String, Rect> out = new HashMap<>();
        Unknown automation = null;
        Unknown element = null;
        Unknown condition = null;
        Unknown array = null;
        try {
            PointerByReference pbr = new PointerByReference();
            WinNT.HRESULT hr = Ole32.INSTANCE.CoCreateInstance(
                    CLSID_CUIAUTOMATION, null, WTypes.CLSCTX_INPROC_SERVER, IID_IUIAUTOMATION, pbr);
            if (COMUtils.FAILED(hr) || pbr.getValue() == null) {
                log.debug("UIA 생성 실패: 0x{}", Integer.toHexString(hr.intValue()));
                return out;
            }
            automation = new Com(pbr.getValue());

            // IUIAutomation::ElementFromHandle(hwnd, &element)
            PointerByReference pElement = new PointerByReference();
            if (failed(((Com) automation).invokeHr(6, new Pointer(hwnd), pElement)) || pElement.getValue() == null) {
                return out;
            }
            element = new Com(pElement.getValue());

            // IUIAutomation::CreatePropertyCondition(UIA_ControlTypePropertyId, VT_I4(ListItem), &condition)
            VariantByValue controlType = new VariantByValue();
            controlType.setValue(Variant.VT_I4, new WinDef.LONG(UIA_LIST_ITEM_CONTROL_TYPE));
            PointerByReference pCondition = new PointerByReference();
            if (failed(((Com) automation).invokeHr(23, UIA_CONTROL_TYPE_PROPERTY, controlType, pCondition))
                    || pCondition.getValue() == null) {
                return out;
            }
            condition = new Com(pCondition.getValue());

            // IUIAutomationElement::FindAll(TreeScope_Descendants, condition, &array)
            PointerByReference pArray = new PointerByReference();
            if (failed(((Com) element).invokeHr(6, TREE_SCOPE_DESCENDANTS, condition.getPointer(), pArray))
                    || pArray.getValue() == null) {
                return out;
            }
            array = new Com(pArray.getValue());

            // IUIAutomationElementArray::get_Length / GetElement
            IntByReference length = new IntByReference();
            if (failed(((Com) array).invokeHr(3, length))) {
                return out;
            }
            int n = Math.min(length.getValue(), MAX_ITEMS);
            for (int i = 0; i < n; i++) {
                PointerByReference pItem = new PointerByReference();
                if (failed(((Com) array).invokeHr(4, i, pItem)) || pItem.getValue() == null) {
                    continue;
                }
                Com item = new Com(pItem.getValue());
                try {
                    String name = nameOf(item);
                    Rect rect = boundsOf(item);
                    if (name == null || name.isBlank() || rect == null) {
                        continue;
                    }
                    // 표시 이름 충돌(확장자 숨김으로 같은 stem)은 매칭이 모호하므로 버린다
                    if (out.containsKey(name)) {
                        out.put(name, null);
                    } else {
                        out.put(name, rect);
                    }
                } finally {
                    item.Release();
                }
            }
            out.values().removeIf(java.util.Objects::isNull);
            return out;
        } catch (Throwable t) {
            log.warn("UIA 항목 좌표 조회 실패 — bounds 없이 계속한다: {}", t.toString());
            return out;
        } finally {
            release(array);
            release(condition);
            release(element);
            release(automation);
        }
    }

    /** IUIAutomationElement::GetCurrentPropertyValue(UIA_NamePropertyId) */
    private static String nameOf(Com item) {
        Variant.VARIANT v = new Variant.VARIANT();
        if (failed(item.invokeHr(10, UIA_NAME_PROPERTY, v))) {
            return null;
        }
        try {
            Object value = v.getValue();
            if (value instanceof WTypes.BSTR b) {
                return b.getValue();
            }
            return value == null ? null : String.valueOf(value);
        } finally {
            LateDispatchFree.clear(v);
        }
    }

    /** GetCurrentPropertyValue(UIA_BoundingRectanglePropertyId) — VT_ARRAY|VT_R8 [left, top, width, height] */
    private static Rect boundsOf(Com item) {
        Variant.VARIANT v = new Variant.VARIANT();
        if (failed(item.invokeHr(10, UIA_BOUNDING_RECTANGLE_PROPERTY, v))) {
            return null;
        }
        try {
            double[] r = doubles(v);
            if (r == null || r.length < 4) {
                return null;
            }
            int w = (int) Math.round(r[2]);
            int h = (int) Math.round(r[3]);
            if (w <= 0 || h <= 0) {
                return null; // 오프스크린(가상화된) 항목
            }
            return new Rect((int) Math.round(r[0]), (int) Math.round(r[1]), w, h);
        } finally {
            LateDispatchFree.clear(v);
        }
    }

    private static double[] doubles(Variant.VARIANT v) {
        try {
            Object value = v.getValue();
            OaIdl.SAFEARRAY sa = null;
            if (value instanceof OaIdl.SAFEARRAY s) {
                sa = s;
            } else {
                // getValue 가 배열을 다루지 못하는 JNA 버전 폴백 — VARIANT 레이아웃상 데이터 유니온은 오프셋 8
                Pointer p = v.getPointer().getPointer(8);
                if (p != null) {
                    sa = new OaIdl.SAFEARRAY(p);
                    sa.read();
                }
            }
            if (sa == null) {
                return null;
            }
            Object arr = OaIdlUtil.toPrimitiveArray(sa, false);
            if (arr instanceof double[] d) {
                return d;
            }
            if (arr instanceof Object[] boxed) {
                double[] d = new double[boxed.length];
                for (int i = 0; i < boxed.length; i++) {
                    d[i] = boxed[i] instanceof Number num ? num.doubleValue() : 0d;
                }
                return d;
            }
            return null;
        } catch (Throwable t) {
            return null;
        }
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

    /** COM 메서드에 값으로 넘기는 VARIANT (x64 에선 JNA 가 ABI 규칙대로 복사 전달한다). */
    private static final class VariantByValue extends Variant.VARIANT implements Structure.ByValue {
    }

    /** OleAuto.VariantClear 로컬 헬퍼 (LateDispatch 와 순환 참조를 피하려고 분리). */
    private static final class LateDispatchFree {
        static void clear(Variant.VARIANT v) {
            try {
                com.sun.jna.platform.win32.OleAuto.INSTANCE.VariantClear(v);
            } catch (Throwable ignored) {
            }
        }
    }
}
