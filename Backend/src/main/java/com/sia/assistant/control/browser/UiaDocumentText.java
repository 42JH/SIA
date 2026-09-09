package com.sia.assistant.control.browser;

import com.sia.assistant.control.com.ComRef;
import com.sun.jna.Pointer;
import com.sun.jna.Structure;
import com.sun.jna.platform.win32.COM.COMUtils;
import com.sun.jna.platform.win32.Guid;
import com.sun.jna.platform.win32.OleAuto;
import com.sun.jna.platform.win32.Ole32;
import com.sun.jna.platform.win32.Variant;
import com.sun.jna.platform.win32.WTypes;
import com.sun.jna.platform.win32.WinDef;
import com.sun.jna.platform.win32.WinNT;
import com.sun.jna.ptr.PointerByReference;
import java.util.Locale;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

/**
 * UIA 로 브라우저 창의 문서(Document) 텍스트·제목·URL 을 읽는다 — 확장이 없을 때의 본문 공급원.
 * ★ ComWorker 스레드에서만 호출한다. 전 과정 best-effort — 실패하면 null.
 *
 * <p>브라우저(Chromium 계열)는 UIA 클라이언트가 붙는 순간 렌더러 접근성 트리를 켠다. 그래서 첫 호출에서
 * Document 를 못 찾는 경우가 있어 한 번 더 시도한다. 트리가 켜지면 브라우저에 상시 성능 비용이 남는다 —
 * 그래서 이 경로는 dom_text 요청이 실제로 올 때만 탄다 (기동이나 폴링으로 미리 켜지 않는다).
 *
 * <p>vtable 인덱스는 UIAutomationClient.h 선언 순서다:
 *   IUIAutomation.ElementFromHandle=6, CreatePropertyCondition=23
 *   IUIAutomationElement.FindFirst=5, GetCurrentPropertyValue=10, GetCurrentPattern=16
 *   IUIAutomationTextPattern.get_DocumentRange=7
 *   IUIAutomationTextRange.GetText=12
 */
final class UiaDocumentText {

    private static final Logger log = LoggerFactory.getLogger(UiaDocumentText.class);

    private static final Guid.CLSID CLSID_CUIAUTOMATION =
            new Guid.CLSID("{FF48DBA4-60EF-4201-AA87-54103EEF594E}");
    private static final Guid.IID IID_IUIAUTOMATION =
            new Guid.IID("{30CBE57D-D9D0-452A-AB13-7AC5AC4825EE}");

    private static final int TREE_SCOPE_DESCENDANTS = 4;
    private static final int UIA_CONTROL_TYPE_PROPERTY = 30003;
    private static final int UIA_NAME_PROPERTY = 30005;
    private static final int UIA_VALUE_VALUE_PROPERTY = 30045;
    private static final int UIA_DOCUMENT_CONTROL_TYPE = 50030;
    private static final int UIA_TEXT_PATTERN = 10014;

    /**
     * 접근성 트리 예열 대기 — 첫 시도가 비면 이 간격만큼 자고 다시 본다 (총 3회 시도).
     * ★ 개발기에서는 첫 시도가 늘 성공해 이 경로가 검증되지 않았다. Chromium 은 시스템에 AT 클라이언트가
     * 있으면 기동 때 접근성을 미리 켜는데, 그런 클라이언트가 하나도 없는 PC 에서 얼마나 걸리는지는 모른다.
     * 그래서 여유 있게 두 번 더 보고, 재시도로 성공하면 INFO 로 남긴다 — 현장 로그가 유일한 관측 수단이다.
     */
    private static final long[] WARMUP_WAITS_MS = {600, 1500};

    /** url 은 없어도 성립한다 (Chromium 은 Document 의 Value 에 주소를 싣지만 다른 엔진은 안 실을 수 있다). */
    record Document(String url, String title, String text) {
    }

    private UiaDocumentText() {
    }

    static Document read(long hwnd) {
        ComRef automation = null;
        try {
            PointerByReference pbr = new PointerByReference();
            WinNT.HRESULT hr = Ole32.INSTANCE.CoCreateInstance(
                    CLSID_CUIAUTOMATION, null, WTypes.CLSCTX_INPROC_SERVER, IID_IUIAUTOMATION, pbr);
            if (COMUtils.FAILED(hr) || pbr.getValue() == null) {
                log.debug("UIA 생성 실패: 0x{}", Integer.toHexString(hr.intValue()));
                return null;
            }
            automation = new ComRef(pbr.getValue());

            Document document = readOnce(automation, hwnd);
            if (document != null) {
                return document;
            }
            // Chromium 이 방금 접근성 트리를 켜기 시작했을 수 있다 — 간격을 늘려 가며 다시 본다
            for (int i = 0; i < WARMUP_WAITS_MS.length; i++) {
                Thread.sleep(WARMUP_WAITS_MS[i]);
                document = readOnce(automation, hwnd);
                if (document != null) {
                    log.info("접근성 트리 예열에 재시도 {}회가 필요했다 (대기 {}ms)", i + 1, WARMUP_WAITS_MS[i]);
                    return document;
                }
            }
            return null;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return null;
        } catch (Throwable t) {
            log.warn("UIA 문서 읽기 실패: {}", t.toString());
            return null;
        } finally {
            ComRef.release(automation);
        }
    }

    private static Document readOnce(ComRef automation, long hwnd) {
        ComRef element = null;
        ComRef condition = null;
        ComRef document = null;
        ComRef textPattern = null;
        ComRef range = null;
        try {
            // IUIAutomation::ElementFromHandle(hwnd, &element)
            PointerByReference pElement = new PointerByReference();
            if (ComRef.failed(automation.invokeHr(6, new Pointer(hwnd), pElement)) || pElement.getValue() == null) {
                return null;
            }
            element = new ComRef(pElement.getValue());

            // IUIAutomation::CreatePropertyCondition(UIA_ControlTypePropertyId, VT_I4(Document), &condition)
            VariantByValue controlType = new VariantByValue();
            controlType.setValue(Variant.VT_I4, new WinDef.LONG(UIA_DOCUMENT_CONTROL_TYPE));
            PointerByReference pCondition = new PointerByReference();
            if (ComRef.failed(automation.invokeHr(23, UIA_CONTROL_TYPE_PROPERTY, controlType, pCondition))
                    || pCondition.getValue() == null) {
                return null;
            }
            condition = new ComRef(pCondition.getValue());

            // IUIAutomationElement::FindFirst(TreeScope_Descendants, condition, &document)
            PointerByReference pDocument = new PointerByReference();
            if (ComRef.failed(element.invokeHr(5, TREE_SCOPE_DESCENDANTS, condition.getPointer(), pDocument))
                    || pDocument.getValue() == null) {
                return null; // 아직 접근성 트리가 없다 — 호출자가 재시도한다
            }
            document = new ComRef(pDocument.getValue());

            // IUIAutomationElement::GetCurrentPattern(UIA_TextPatternId, &textPattern)
            PointerByReference pPattern = new PointerByReference();
            if (ComRef.failed(document.invokeHr(16, UIA_TEXT_PATTERN, pPattern)) || pPattern.getValue() == null) {
                log.debug("문서가 TextPattern 을 지원하지 않는다");
                return null;
            }
            textPattern = new ComRef(pPattern.getValue());

            // IUIAutomationTextPattern::get_DocumentRange(&range)
            PointerByReference pRange = new PointerByReference();
            if (ComRef.failed(textPattern.invokeHr(7, pRange)) || pRange.getValue() == null) {
                return null;
            }
            range = new ComRef(pRange.getValue());

            // IUIAutomationTextRange::GetText(-1, &text) — -1 은 범위 전체
            PointerByReference pText = new PointerByReference();
            if (ComRef.failed(range.invokeHr(12, -1, pText)) || pText.getValue() == null) {
                return null;
            }
            String text = bstr(pText.getValue());
            if (text == null || text.isBlank()) {
                return null;
            }
            return new Document(urlOf(document), stringProperty(document, UIA_NAME_PROPERTY), text);
        } catch (Throwable t) {
            log.debug("UIA 문서 읽기 시도 실패: {}", t.toString());
            return null;
        } finally {
            ComRef.release(range);
            ComRef.release(textPattern);
            ComRef.release(document);
            ComRef.release(condition);
            ComRef.release(element);
        }
    }

    /** Chromium 은 Document 의 Value 에 현재 주소를 싣는다. http(s) 가 아니면 없는 셈 친다. */
    private static String urlOf(ComRef document) {
        String value = stringProperty(document, UIA_VALUE_VALUE_PROPERTY);
        if (value == null) {
            return null;
        }
        String lower = value.toLowerCase(Locale.ROOT);
        return (lower.startsWith("http://") || lower.startsWith("https://")) ? value : null;
    }

    /** IUIAutomationElement::GetCurrentPropertyValue(propertyId) 의 문자열 값. 없으면 null. */
    private static String stringProperty(ComRef element, int propertyId) {
        Variant.VARIANT v = new Variant.VARIANT();
        if (ComRef.failed(element.invokeHr(10, propertyId, v))) {
            return null;
        }
        try {
            Object value = v.getValue();
            if (value instanceof WTypes.BSTR b) {
                String s = b.getValue();
                return s == null || s.isBlank() ? null : s;
            }
            if (value == null) {
                return null;
            }
            String s = String.valueOf(value);
            return s.isBlank() ? null : s;
        } catch (Throwable t) {
            return null;
        } finally {
            try {
                OleAuto.INSTANCE.VariantClear(v);
            } catch (Throwable ignored) {
                // 해제 실패는 이 호출의 결과를 바꾸지 않는다
            }
        }
    }

    /** BSTR 아웃 파라미터를 읽고 해제한다 — 해제를 빼먹으면 페이지마다 수십 KB 씩 샌다. */
    private static String bstr(Pointer p) {
        WTypes.BSTR b = new WTypes.BSTR(p);
        try {
            return b.getValue();
        } catch (Throwable t) {
            return null;
        } finally {
            try {
                OleAuto.INSTANCE.SysFreeString(b);
            } catch (Throwable ignored) {
                // 위와 같다 — 해제 실패로 결과를 버리지는 않는다
            }
        }
    }

    /** COM 메서드에 값으로 넘기는 VARIANT (x64 에선 JNA 가 ABI 규칙대로 복사 전달한다). */
    private static final class VariantByValue extends Variant.VARIANT implements Structure.ByValue {
    }
}
