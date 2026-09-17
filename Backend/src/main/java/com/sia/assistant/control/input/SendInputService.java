package com.sia.assistant.control.input;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.control.window.User32Ext;
import com.sun.jna.platform.win32.BaseTSD;
import com.sun.jna.platform.win32.User32;
import com.sun.jna.platform.win32.WinDef;
import com.sun.jna.platform.win32.WinUser;
import java.util.Locale;
import org.springframework.stereotype.Service;

/**
 * JNA SendInput 직접 호출 (java.awt.Robot 금지 — Robot 은 DirectInput 계열 앱에서 씹히고 dwExtraInfo 를 못 찍는다).
 * 모든 합성 입력에 dwExtraInfo=0x4D430001 표식을 남겨 에이전트가 자기 입력을 되받는 루프를 막는다.
 */
@Service
public class SendInputService {

    private static final int WHEEL_DELTA = 120;
    private static final int MOUSEEVENTF_WHEEL = 0x0800;
    private static final int MOUSEEVENTF_HWHEEL = 0x1000;
    /** 'M''C' + 1 — 이 프로세스가 합성한 입력의 표식 */
    private static final long EXTRA_MARKER = 0x4D430001L;
    private static final int VK_SHIFT = 0x10;
    private static final int VK_LEFT = 0x25;
    private static final int VK_RIGHT = 0x27;

    /** dir: up|down(|left|right). clicks 는 1~10 클램프. */
    public void scroll(String dir, int clicks) {
        int c = Math.max(1, Math.min(10, clicks));
        int flags;
        int delta;
        switch (dir == null ? "" : dir.trim().toLowerCase(Locale.ROOT)) {
            case "up" -> {
                flags = MOUSEEVENTF_WHEEL;
                delta = WHEEL_DELTA * c;
            }
            case "down" -> {
                flags = MOUSEEVENTF_WHEEL;
                delta = -WHEEL_DELTA * c;
            }
            case "left" -> {
                flags = MOUSEEVENTF_HWHEEL;
                delta = -WHEEL_DELTA * c;
            }
            case "right" -> {
                flags = MOUSEEVENTF_HWHEEL;
                delta = WHEEL_DELTA * c;
            }
            default -> throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "지원하지 않는 스크롤 방향입니다: " + dir + " (up|down|left|right)");
        }
        WinUser.INPUT[] inputs = (WinUser.INPUT[]) new WinUser.INPUT().toArray(1);
        fillWheel(inputs[0], flags, delta);
        send(inputs);
    }

    /** key: PLAY_PAUSE | NEXT | PREV | MUTE | VOL_UP | VOL_DOWN → VK_MEDIA_* / VK_VOLUME_* down+up */
    public void mediaKey(String key) {
        int vk = switch (key == null ? "" : key.trim().toUpperCase(Locale.ROOT)) {
            case "PLAY_PAUSE" -> 0xB3; // VK_MEDIA_PLAY_PAUSE
            case "NEXT" -> 0xB0;       // VK_MEDIA_NEXT_TRACK
            case "PREV" -> 0xB1;       // VK_MEDIA_PREV_TRACK
            case "MUTE" -> 0xAD;       // VK_VOLUME_MUTE
            case "VOL_UP" -> 0xAF;     // VK_VOLUME_UP
            case "VOL_DOWN" -> 0xAE;   // VK_VOLUME_DOWN
            default -> throw new ApiException(ErrorCode.INVALID_REQUEST, "지원하지 않는 미디어 키입니다: " + key);
        };
        pressAndRelease(new int[]{vk});
    }

    /**
     * dir: left|right 방향키를 repeat 번 눌렀다 뗀다 (1~10 클램프). 미디어 탐색(앞으로/뒤로)의 유일한 경로다 —
     * 시스템 미디어 키에는 탐색에 해당하는 가상 키가 없다.
     * ★ 방향키는 확장 키다. KEYEVENTF_EXTENDEDKEY 가 없으면 스캔 코드가 넘버패드 쪽으로 잡혀
     * 스캔 코드로 키를 읽는 앱(브라우저의 event.code 등)이 방향키로 보지 않는다.
     */
    public void arrowKey(String dir, int repeat) {
        int vk = switch (dir == null ? "" : dir.trim().toLowerCase(Locale.ROOT)) {
            case "left" -> VK_LEFT;
            case "right" -> VK_RIGHT;
            default -> throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "지원하지 않는 방향키입니다: " + dir + " (left|right)");
        };
        int n = Math.max(1, Math.min(10, repeat));
        WinUser.INPUT[] inputs = (WinUser.INPUT[]) new WinUser.INPUT().toArray(n * 2);
        for (int i = 0; i < n; i++) {
            fillKey(inputs[i * 2], vk, false, true);
            fillKey(inputs[i * 2 + 1], vk, true, true);
        }
        send(inputs);
    }

    /** 예: Shift+N. down(mods) → down(vk) → up(vk) → up(mods 역순) */
    public void shortcut(int[] modifierVks, int vk) {
        int[] seq = new int[(modifierVks == null ? 0 : modifierVks.length) + 1];
        for (int i = 0; i < seq.length - 1; i++) {
            seq[i] = modifierVks[i];
        }
        seq[seq.length - 1] = vk;
        pressAndRelease(seq);
    }

    /** 단일 문자 키 (유튜브 K/M/J/L 등). VkKeyScan 이 Shift 를 요구하면 Shift 조합으로 보낸다. */
    public void key(char c) {
        short scan = User32Ext.INSTANCE.VkKeyScan(c);
        if (scan == -1) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "키로 변환할 수 없는 문자입니다: " + c);
        }
        int vk = scan & 0xFF;
        boolean needShift = (scan & 0x0100) != 0;
        if (needShift) {
            shortcut(new int[]{VK_SHIFT}, vk);
        } else {
            pressAndRelease(new int[]{vk});
        }
    }

    /** 문자 → 가상 키 코드 (shortcut 조합용) */
    public int vkForChar(char c) {
        short scan = User32Ext.INSTANCE.VkKeyScan(c);
        if (scan == -1) {
            throw new ApiException(ErrorCode.INVALID_REQUEST, "키로 변환할 수 없는 문자입니다: " + c);
        }
        return scan & 0xFF;
    }

    // ------------------------------------------------------------------ 내부

    /** 순서대로 down, 역순으로 up — 조합 키의 표준 순서 */
    private void pressAndRelease(int[] vks) {
        WinUser.INPUT[] inputs = (WinUser.INPUT[]) new WinUser.INPUT().toArray(vks.length * 2);
        for (int i = 0; i < vks.length; i++) {
            fillKey(inputs[i], vks[i], false);
        }
        for (int i = 0; i < vks.length; i++) {
            fillKey(inputs[vks.length + i], vks[vks.length - 1 - i], true);
        }
        send(inputs);
    }

    private void fillKey(WinUser.INPUT in, int vk, boolean up) {
        fillKey(in, vk, up, false);
    }

    private void fillKey(WinUser.INPUT in, int vk, boolean up, boolean extended) {
        int flags = (up ? WinUser.KEYBDINPUT.KEYEVENTF_KEYUP : 0)
                | (extended ? WinUser.KEYBDINPUT.KEYEVENTF_EXTENDEDKEY : 0);
        in.type = new WinDef.DWORD(WinUser.INPUT.INPUT_KEYBOARD);
        in.input.setType("ki");
        in.input.ki.wVk = new WinDef.WORD(vk);
        in.input.ki.wScan = new WinDef.WORD(0);
        in.input.ki.dwFlags = new WinDef.DWORD(flags);
        in.input.ki.time = new WinDef.DWORD(0);
        in.input.ki.dwExtraInfo = new BaseTSD.ULONG_PTR(EXTRA_MARKER);
    }

    private void fillWheel(WinUser.INPUT in, int flags, int delta) {
        in.type = new WinDef.DWORD(WinUser.INPUT.INPUT_MOUSE);
        in.input.setType("mi");
        in.input.mi.dx = new WinDef.LONG(0);
        in.input.mi.dy = new WinDef.LONG(0);
        // mouseData 는 DWORD — 음수 델타는 32비트 무부호 표현으로 넣는다
        in.input.mi.mouseData = new WinDef.DWORD(Integer.toUnsignedLong(delta));
        in.input.mi.dwFlags = new WinDef.DWORD(flags);
        in.input.mi.time = new WinDef.DWORD(0);
        in.input.mi.dwExtraInfo = new BaseTSD.ULONG_PTR(EXTRA_MARKER);
    }

    private void send(WinUser.INPUT[] inputs) {
        WinDef.DWORD sent = User32.INSTANCE.SendInput(new WinDef.DWORD(inputs.length), inputs, inputs[0].size());
        if (sent.intValue() != inputs.length) {
            throw new ApiException(ErrorCode.INTERNAL_ERROR, "입력 합성에 실패했습니다. 다시 시도해주세요");
        }
    }
}
