package com.sia.assistant.control.window;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import com.sun.jna.Native;
import com.sun.jna.Pointer;
import com.sun.jna.platform.win32.Advapi32;
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
import java.util.function.BooleanSupplier;
import java.util.function.Predicate;
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
    private static final String FOREGROUND_MESSAGE =
            "창을 앞으로 가져오지 못했습니다. 작업 표시줄에서 깜빡이는 창을 눌러 주세요";
    private static final String SHOW_FAILED_MESSAGE = "창 상태를 바꾸지 못했습니다. 잠시 후 다시 시도해주세요";

    /** 창 조작이 반영될 때까지 기다리는 시간 — 성공이면 첫 폴에 끝나고, 이 시간을 다 쓰는 건 실패뿐이다. */
    private static final long SETTLE_TIMEOUT_MS = 400;
    private static final long SETTLE_POLL_MS = 10;
    private static final int FLASHW_ALL = 0x00000003;
    /** 창이 앞으로 올 때까지 계속 깜빡인다 */
    private static final int FLASHW_TIMERNOFG = 0x0000000C;
    private static final int FLASH_COUNT = 3;

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

    /**
     * 최소화 상태면 SW_RESTORE 후 전면화한다.
     *
     * <p>★ 반환값이 아니라 <b>결과</b>(GetForegroundWindow)로 판정한다 — AttachThreadInput 경로는
     * SetForegroundWindow 가 false 를 돌려주고도 실제로 창을 앞으로 가져온다(실측).
     *
     * <p>★ BE 는 백그라운드 프로세스라 포그라운드 권한이 없어 <b>1차 시도는 평상시에 실패한다</b>
     * (Windows 의 포그라운드 잠금. 관리자 권한과 무관하다). 그래서 실패하면 현재 포그라운드 창의
     * 스레드에 입력 큐를 잠깐 붙여 다시 시도한다. 사용자가 음성으로 직접 요청한 전환이므로
     * 이 우회는 "동의 없는 탈취"에 해당하지 않는다.
     */
    public void focus(long hwnd) {
        WinDef.HWND h = hwnd(hwnd);
        if (User32Ext.INSTANCE.IsIconic(h)) {
            User32.INSTANCE.ShowWindow(h, WinUser.SW_RESTORE);
        }
        User32.INSTANCE.SetForegroundWindow(h);
        if (await(() -> foregroundHwnd() == hwnd)) {
            return;
        }
        attachAndRaise(h);
        if (await(() -> foregroundHwnd() == hwnd)) {
            return;
        }
        if (blockedByElevation(hwnd)) {
            throw new BlockedException(ErrorCode.ELEVATED_WINDOW, ELEVATED_MESSAGE);
        }
        // 앞으로 못 가져왔으면 작업 표시줄에서 깜빡이게 둔다 — 사용자에게 다음 행동이 남는다
        flash(h);
        throw new BlockedException(ErrorCode.FOREGROUND_BLOCKED, FOREGROUND_MESSAGE);
    }

    public void minimize(long hwnd) {
        applyShow(hwnd, WinUser.SW_MINIMIZE, h -> User32Ext.INSTANCE.IsIconic(h));
    }

    public void maximize(long hwnd) {
        applyShow(hwnd, WinUser.SW_MAXIMIZE, h -> User32Ext.INSTANCE.IsZoomed(h));
    }

    public void restore(long hwnd) {
        applyShow(hwnd, WinUser.SW_RESTORE,
                h -> !User32Ext.INSTANCE.IsIconic(h) && !User32Ext.INSTANCE.IsZoomed(h));
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

    /**
     * ★ ShowWindow 의 반환값은 성공 여부가 아니라 <b>이전 표시 상태</b>다 — 그걸 보면 성공도 실패도
     * 알 수 없어 관리자 권한 창에서 조용히 아무 일도 안 일어나던 자리다. 상태가 실제로 바뀌었는지로 판정한다.
     */
    private void applyShow(long hwnd, int command, Predicate<WinDef.HWND> reached) {
        WinDef.HWND h = hwnd(hwnd);
        if (reached.test(h)) {
            return;
        }
        User32.INSTANCE.ShowWindow(h, command);
        if (await(() -> reached.test(h))) {
            return;
        }
        if (blockedByElevation(hwnd)) {
            throw new BlockedException(ErrorCode.ELEVATED_WINDOW, ELEVATED_MESSAGE);
        }
        throw new ApiException(ErrorCode.INTERNAL_ERROR, SHOW_FAILED_MESSAGE);
    }

    /** 창 조작은 곧바로 반영되지 않는다(다른 프로세스의 메시지 루프를 거친다) — 조건이 설 때까지 짧게 기다린다. */
    private static boolean await(BooleanSupplier condition) {
        long deadline = System.currentTimeMillis() + SETTLE_TIMEOUT_MS;
        while (true) {
            if (condition.getAsBoolean()) {
                return true;
            }
            if (System.currentTimeMillis() >= deadline) {
                return false;
            }
            try {
                Thread.sleep(SETTLE_POLL_MS);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                return condition.getAsBoolean();
            }
        }
    }

    /**
     * 현재 포그라운드 창의 스레드에 우리 입력 큐를 잠깐 붙이면 그 동안은 포그라운드 권한을 함께 쓴다.
     * ★ 반드시 떼어 낸다 — 붙은 채로 남으면 두 스레드의 입력 처리가 계속 묶인다.
     * 관리자 권한 창에는 UIPI 로 attach 자체가 막히므로 자연히 실패하고 호출자가 원인을 가른다.
     */
    private void attachAndRaise(WinDef.HWND h) {
        long foreground = foregroundHwnd();
        int foregroundThread = foreground == 0L ? 0
                : User32.INSTANCE.GetWindowThreadProcessId(hwnd(foreground), new IntByReference());
        int self = Kernel32.INSTANCE.GetCurrentThreadId();
        boolean attached = foregroundThread != 0 && foregroundThread != self
                && User32.INSTANCE.AttachThreadInput(
                        new WinDef.DWORD(self), new WinDef.DWORD(foregroundThread), true);
        try {
            User32.INSTANCE.SetForegroundWindow(h);
            User32.INSTANCE.BringWindowToTop(h);
        } finally {
            if (attached) {
                User32.INSTANCE.AttachThreadInput(
                        new WinDef.DWORD(self), new WinDef.DWORD(foregroundThread), false);
            }
        }
    }

    /** 포그라운드로 못 올릴 때의 정석 대체 동작 — 작업 표시줄 단추를 깜빡여 사용자가 직접 누르게 한다. */
    private static void flash(WinDef.HWND h) {
        WinUser.FLASHWINFO info = new WinUser.FLASHWINFO();
        info.cbSize = info.size();
        info.hWnd = h;
        info.dwFlags = FLASHW_ALL | FLASHW_TIMERNOFG;
        info.uCount = FLASH_COUNT;
        info.dwTimeout = 0;
        User32.INSTANCE.FlashWindowEx(info);
    }

    /**
     * 대상이 우리보다 높은 권한이라 UIPI 로 조작이 막히는 경우인지. 토큰을 열지 못하는 것 자체가 막혔다는 신호다.
     * ★ 이 판정이 있어야 "관리자 권한으로 실행된 창" 메시지가 진짜 그 경우에만 나간다 —
     * 예전에는 포그라운드 잠금(권한과 무관)까지 같은 메시지로 보고했다.
     */
    static boolean blockedByElevation(long hwnd) { // 가시성은 라이브 테스트가 오판(항상 true)을 잡기 위한 것
        if (elevated(Kernel32.INSTANCE.GetCurrentProcess())) {
            return false; // 우리가 이미 관리자면 권한 때문에 막힌 게 아니다
        }
        IntByReference pid = new IntByReference();
        User32.INSTANCE.GetWindowThreadProcessId(hwnd(hwnd), pid);
        if (pid.getValue() == 0) {
            return false;
        }
        WinNT.HANDLE process =
                Kernel32.INSTANCE.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid.getValue());
        if (process == null) {
            return true; // 열지도 못하는 프로세스 — 우리 권한 밖이다
        }
        try {
            return elevated(process);
        } finally {
            Kernel32.INSTANCE.CloseHandle(process);
        }
    }

    private static boolean elevated(WinNT.HANDLE process) {
        WinNT.HANDLEByReference token = new WinNT.HANDLEByReference();
        if (!Advapi32.INSTANCE.OpenProcessToken(process, WinNT.TOKEN_QUERY, token)) {
            return true; // 토큰조차 못 여는 상대는 더 높은 권한으로 본다
        }
        try {
            WinNT.TOKEN_ELEVATION elevation = new WinNT.TOKEN_ELEVATION();
            IntByReference size = new IntByReference();
            if (!Advapi32.INSTANCE.GetTokenInformation(token.getValue(),
                    WinNT.TOKEN_INFORMATION_CLASS.TokenElevation, elevation, elevation.size(), size)) {
                return false;
            }
            elevation.read();
            return elevation.TokenIsElevated != 0;
        } finally {
            Kernel32.INSTANCE.CloseHandle(token.getValue());
        }
    }

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
