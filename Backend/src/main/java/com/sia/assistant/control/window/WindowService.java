package com.sia.assistant.control.window;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import com.sun.jna.Native;
import com.sun.jna.Pointer;
import com.sun.jna.platform.win32.Kernel32;
import com.sun.jna.platform.win32.User32;
import com.sun.jna.platform.win32.WinDef;
import com.sun.jna.platform.win32.WinNT;
import com.sun.jna.platform.win32.WinUser;
import com.sun.jna.ptr.IntByReference;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import org.springframework.stereotype.Service;

/**
 * JNA User32 기반 창 제어. hwnd 는 이 계층 안에서만 다루고, LLM 에는 RefResolver 가 win:N ref 로 감춘다.
 */
@Service
public class WindowService {

    /** state: NORMAL | MINIMIZED | MAXIMIZED */
    public record WindowInfo(long hwnd, String title, String app, String state) {
    }

    private static final int WS_EX_TOOLWINDOW = 0x00000080;
    /** 앱 이름 조회에 필요한 최소 권한 — 관리자 권한 프로세스도 이 권한으로는 대부분 열린다 */
    private static final int PROCESS_QUERY_LIMITED_INFORMATION = 0x1000;

    private static final String ELEVATED_MESSAGE = "관리자 권한으로 실행된 창은 제어할 수 없습니다";

    /** 보이는 창 + 제목 있는 것 + WS_EX_TOOLWINDOW 제외. EnumWindows 의 Z 순서(앞쪽 먼저)를 유지한다. */
    public List<WindowInfo> list() {
        List<WindowInfo> out = new ArrayList<>();
        // Electron 앱은 클래스명이 전부 Chrome_WidgetWin_1 이라 프로세스 파일명으로 갈라야 한다.
        // 같은 pid 를 창마다 다시 OpenProcess 하지 않도록 한 번의 열거 안에서 캐시한다.
        Map<Integer, String> appByPid = new HashMap<>();
        User32.INSTANCE.EnumWindows((hwnd, data) -> {
            if (!User32.INSTANCE.IsWindowVisible(hwnd)) {
                return true;
            }
            int exStyle = User32.INSTANCE.GetWindowLong(hwnd, WinUser.GWL_EXSTYLE);
            if ((exStyle & WS_EX_TOOLWINDOW) != 0) {
                return true;
            }
            int len = User32.INSTANCE.GetWindowTextLength(hwnd);
            if (len <= 0) {
                return true;
            }
            char[] buf = new char[len + 1];
            User32.INSTANCE.GetWindowText(hwnd, buf, buf.length);
            String title = Native.toString(buf);
            if (title.isBlank()) {
                return true;
            }
            IntByReference pid = new IntByReference();
            User32.INSTANCE.GetWindowThreadProcessId(hwnd, pid);
            String app = appByPid.computeIfAbsent(pid.getValue(), WindowService::appNameOf);
            out.add(new WindowInfo(Pointer.nativeValue(hwnd.getPointer()), title, app, stateOf(hwnd)));
            return true;
        }, Pointer.NULL);
        return out;
    }

    /** 최소화 상태면 SW_RESTORE 후 전면화한다. */
    public void focus(long hwnd) {
        WinDef.HWND h = hwnd(hwnd);
        if (User32Ext.INSTANCE.IsIconic(h)) {
            User32.INSTANCE.ShowWindow(h, WinUser.SW_RESTORE);
        }
        if (!User32.INSTANCE.SetForegroundWindow(h)) {
            throw new BlockedException(ErrorCode.ELEVATED_WINDOW, ELEVATED_MESSAGE);
        }
    }

    public void minimize(long hwnd) {
        User32.INSTANCE.ShowWindow(hwnd(hwnd), WinUser.SW_MINIMIZE);
    }

    public void maximize(long hwnd) {
        User32.INSTANCE.ShowWindow(hwnd(hwnd), WinUser.SW_MAXIMIZE);
    }

    public void restore(long hwnd) {
        User32.INSTANCE.ShowWindow(hwnd(hwnd), WinUser.SW_RESTORE);
    }

    /**
     * preset: LEFT_HALF | RIGHT_HALF | CENTER. 좌표는 창이 속한 모니터의 rcWork 기준.
     * 전부 SetWindowPos 라 관리자 창이면 항상 ELEVATED_WINDOW 다 — 이 도구의 실패 모드는 하나다.
     * 상태 전환(최대화·복원)은 ShowWindow 를 쓰는 maximize/restore 가 맡는다: 프리셋으로 겹쳐 받지 않는다.
     */
    public void resize(long hwnd, String preset) {
        String p = preset == null ? "" : preset.trim().toUpperCase(Locale.ROOT);
        switch (p) {
            case "LEFT_HALF", "RIGHT_HALF", "CENTER" -> {
                WinDef.HWND h = hwnd(hwnd);
                // 최대화/최소화 상태에서 SetWindowPos 를 하면 배치가 어긋난다 — 먼저 보통 상태로.
                if (User32Ext.INSTANCE.IsIconic(h) || User32Ext.INSTANCE.IsZoomed(h)) {
                    User32.INSTANCE.ShowWindow(h, WinUser.SW_RESTORE);
                }
                WinDef.RECT work = workAreaOf(h);
                int workW = work.right - work.left;
                int workH = work.bottom - work.top;
                int x;
                int y;
                int w;
                int hgt;
                switch (p) {
                    case "LEFT_HALF" -> {
                        x = work.left;
                        y = work.top;
                        w = workW / 2;
                        hgt = workH;
                    }
                    case "RIGHT_HALF" -> {
                        x = work.left + workW / 2;
                        y = work.top;
                        w = workW - workW / 2;
                        hgt = workH;
                    }
                    default -> { // CENTER — 현재 크기 유지(작업 영역보다 크면 축소), 중앙 배치
                        WinDef.RECT rect = new WinDef.RECT();
                        User32.INSTANCE.GetWindowRect(h, rect);
                        w = Math.min(rect.right - rect.left, workW);
                        hgt = Math.min(rect.bottom - rect.top, workH);
                        x = work.left + (workW - w) / 2;
                        y = work.top + (workH - hgt) / 2;
                    }
                }
                if (!User32.INSTANCE.SetWindowPos(h, null, x, y, w, hgt,
                        WinUser.SWP_NOZORDER | WinUser.SWP_SHOWWINDOW)) {
                    throw new BlockedException(ErrorCode.ELEVATED_WINDOW, ELEVATED_MESSAGE);
                }
            }
            default -> throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "지원하지 않는 창 크기 프리셋입니다: " + preset + " (LEFT_HALF|RIGHT_HALF|CENTER)");
        }
    }

    /** WM_CLOSE 를 보낸다 — 앱이 저장 확인 다이얼로그를 띄울 기회를 준다. 강제 종료가 아니다. */
    public void close(long hwnd) {
        if (!User32Ext.INSTANCE.PostMessage(hwnd(hwnd), WinUser.WM_CLOSE,
                new WinDef.WPARAM(0), new WinDef.LPARAM(0))) {
            throw new BlockedException(ErrorCode.ELEVATED_WINDOW, ELEVATED_MESSAGE);
        }
    }

    public long foregroundHwnd() {
        WinDef.HWND h = User32.INSTANCE.GetForegroundWindow();
        return h == null ? 0L : Pointer.nativeValue(h.getPointer());
    }

    /** 창이 죽었으면 "" */
    public String titleOf(long hwnd) {
        WinDef.HWND h = hwnd(hwnd);
        if (!User32.INSTANCE.IsWindow(h)) {
            return "";
        }
        int len = User32.INSTANCE.GetWindowTextLength(h);
        if (len <= 0) {
            return "";
        }
        char[] buf = new char[len + 1];
        User32.INSTANCE.GetWindowText(h, buf, buf.length);
        return Native.toString(buf);
    }

    public boolean isAlive(long hwnd) {
        return User32.INSTANCE.IsWindow(hwnd(hwnd));
    }

    // ------------------------------------------------------------------ 내부

    private static WinDef.HWND hwnd(long value) {
        return new WinDef.HWND(new Pointer(value));
    }

    private static String stateOf(WinDef.HWND h) {
        if (User32Ext.INSTANCE.IsIconic(h)) {
            return "MINIMIZED";
        }
        if (User32Ext.INSTANCE.IsZoomed(h)) {
            return "MAXIMIZED";
        }
        return "NORMAL";
    }

    /** 소문자 실행 파일명(.exe 제거). 열 수 없는 프로세스(보호 프로세스 등)는 "unknown". */
    private static String appNameOf(int pid) {
        WinNT.HANDLE handle = Kernel32.INSTANCE.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid);
        if (handle == null) {
            return "unknown";
        }
        try {
            char[] buf = new char[1024];
            IntByReference size = new IntByReference(buf.length);
            if (!Kernel32.INSTANCE.QueryFullProcessImageName(handle, 0, buf, size)) {
                return "unknown";
            }
            String path = new String(buf, 0, size.getValue());
            String file = path.substring(path.lastIndexOf('\\') + 1).toLowerCase(Locale.ROOT);
            return file.endsWith(".exe") ? file.substring(0, file.length() - 4) : file;
        } finally {
            Kernel32.INSTANCE.CloseHandle(handle);
        }
    }

    private static WinDef.RECT workAreaOf(WinDef.HWND h) {
        WinUser.HMONITOR monitor = User32.INSTANCE.MonitorFromWindow(h, WinUser.MONITOR_DEFAULTTONEAREST);
        WinUser.MONITORINFO info = new WinUser.MONITORINFO();
        User32.INSTANCE.GetMonitorInfo(monitor, info);
        return info.rcWork;
    }
}
