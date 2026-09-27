package com.sia.assistant.control.window;

import com.sun.jna.Native;
import com.sun.jna.platform.win32.WinDef;
import com.sun.jna.win32.StdCallLibrary;
import com.sun.jna.win32.W32APIOptions;

/**
 * jna-platform 5.14 의 User32 인터페이스에 빠져 있는 함수 보충.
 * User32 를 상속하지 않는다 — 상속하면 PostMessage(반환형 void)와 시그니처가 충돌한다.
 */
public interface User32Ext extends StdCallLibrary {

    User32Ext INSTANCE = Native.load("user32", User32Ext.class, W32APIOptions.DEFAULT_OPTIONS);

    boolean IsIconic(WinDef.HWND hWnd);

    boolean IsZoomed(WinDef.HWND hWnd);

    /** W32 함수 매퍼가 VkKeyScanW 로 해소한다. 실패 시 -1. 하위 바이트=VK, 0x0100 비트=Shift 필요. */
    short VkKeyScan(char ch);

    /** User32 의 PostMessage 는 반환형이 void 라 실패(관리자 권한 창 등)를 알 수 없어 다시 선언한다. */
    boolean PostMessage(WinDef.HWND hWnd, int msg, WinDef.WPARAM wParam, WinDef.LPARAM lParam);

    /** system.lock — 워크스테이션 잠금. 실패 시 false. */
    boolean LockWorkStation();
}
