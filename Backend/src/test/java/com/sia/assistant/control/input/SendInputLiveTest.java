package com.sia.assistant.control.input;

import static org.assertj.core.api.Assertions.assertThat;

import com.sun.jna.platform.win32.Kernel32;
import com.sun.jna.platform.win32.User32;
import com.sun.jna.platform.win32.WinDef;
import com.sun.jna.platform.win32.WinUser;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;

/**
 * 합성 방향키가 실제로 어떤 모양으로 나가는지 확인하는 스모크 테스트 — VK 번호 · 확장 키 플래그 ·
 * 반복 횟수 · 자기 입력 표식(dwExtraInfo)은 이것으로만 검증된다 (컴파일은 전부 틀려도 통과한다).
 *
 * <p>저수준 키보드 훅(WH_KEYBOARD_LL)으로 우리가 쏜 키를 가로채 검사하고 <b>삼킨다</b> —
 * 포커스를 빼앗을 필요가 없고, 사용자가 보던 창으로 방향키가 새지도 않는다.
 * 표식이 우리 것이 아닌 입력(사용자의 실제 타자)은 손대지 않고 그대로 흘려보낸다.
 *
 * <p>사용자 세션과 메시지 펌프가 필요해 CI 에서는 돌 수 없다. 기본은 비활성이고
 * {@code ./gradlew test -Dsia.live.input=true --tests '*SendInputLiveTest'} 로만 켠다.
 */
@EnabledIfSystemProperty(named = "sia.live.input", matches = "true")
class SendInputLiveTest {

    private static final int WH_KEYBOARD_LL = 13;
    private static final int WM_KEYDOWN = 0x0100;
    private static final int WM_KEYUP = 0x0101;
    private static final int LLKHF_EXTENDED = 0x01;
    private static final int LLKHF_INJECTED = 0x10;
    private static final int VK_LEFT = 0x25;
    private static final int VK_RIGHT = 0x27;
    /** SendInputService 가 자기 입력에 남기는 표식 */
    private static final long EXTRA_MARKER = 0x4D430001L;
    private static final int PM_REMOVE = 1;
    private static final long PUMP_MS = 1500;
    /** SendInputService 가 연타 사이에 두는 간격 */
    private static final int KEY_GAP_MS = 30;

    private record Event(int message, int vkCode, int flags, int time) {
        boolean down() {
            return message == WM_KEYDOWN;
        }

        boolean extended() {
            return (flags & LLKHF_EXTENDED) != 0;
        }
    }

    @Test
    @DisplayName("forward 3번은 확장 키 플래그가 선 VK_RIGHT down·up 3쌍으로 나간다")
    void rightArrowGoesOutThreeTimes() {
        List<Event> events = capture(() -> new SendInputService().arrowKey("right", 3));

        assertThat(events)
                .withFailMessage("훅이 합성 입력을 하나도 받지 못했습니다 — 메시지 펌프나 훅 설치를 확인하세요")
                .isNotEmpty();
        assertThat(events).hasSize(6);
        assertThat(events).allSatisfy(e -> {
            assertThat(e.vkCode()).isEqualTo(VK_RIGHT);
            // ★ 이 플래그가 빠지면 스캔 코드가 넘버패드로 잡혀 방향키로 안 보는 앱이 생긴다
            assertThat(e.extended()).isTrue();
        });
        assertThat(events.stream().filter(Event::down).count()).isEqualTo(3);
    }

    @Test
    @DisplayName("backward 는 VK_LEFT 로 나가고, down 과 up 이 번갈아 한 쌍씩이다")
    void leftArrowAlternatesDownAndUp() {
        List<Event> events = capture(() -> new SendInputService().arrowKey("left", 2));

        assertThat(events).hasSize(4);
        assertThat(events).allSatisfy(e -> assertThat(e.vkCode()).isEqualTo(VK_LEFT));
        assertThat(events.stream().map(Event::message).toList())
                .containsExactly(WM_KEYDOWN, WM_KEYUP, WM_KEYDOWN, WM_KEYUP);
    }

    @Test
    @DisplayName("10을 넘는 횟수는 10번으로 잘린다 — 실수로 100초를 건너뛰지 않는다")
    void repeatIsClampedToTen() {
        List<Event> events = capture(() -> new SendInputService().arrowKey("right", 50));

        assertThat(events.stream().filter(Event::down).count()).isEqualTo(10);
    }

    @Test
    @DisplayName("연타는 30ms 이상 벌어져 나간다 — 한 번에 몰아 보내면 플레이어가 일부를 흘린다")
    void repeatedTapsAreSpacedApart() {
        List<Event> downs = capture(() -> new SendInputService().arrowKey("right", 4))
                .stream().filter(Event::down).toList();

        assertThat(downs).hasSize(4);
        for (int i = 1; i < downs.size(); i++) {
            int gap = downs.get(i).time() - downs.get(i - 1).time();
            assertThat(gap)
                    .withFailMessage("%d번째와 %d번째 입력 간격이 %dms 입니다 (30ms 이상이어야 함)", i, i + 1, gap)
                    .isGreaterThanOrEqualTo(KEY_GAP_MS);
        }
    }

    /**
     * 훅을 걸고 injection 을 다른 스레드에서 돌린 뒤, 우리 표식이 찍힌 키 이벤트만 모아 돌려준다.
     * 저수준 훅은 설치한 스레드가 메시지를 펌프해야 불린다 — 펌프를 멈추면 Windows 가 훅을 무시한다.
     */
    private List<Event> capture(Runnable injection) {
        List<Event> events = Collections.synchronizedList(new ArrayList<>());
        WinDef.HMODULE module = Kernel32.INSTANCE.GetModuleHandle(null);
        WinDef.HINSTANCE instance = new WinDef.HINSTANCE();
        instance.setPointer(module.getPointer());

        // 람다가 아니라 변수로 잡아 둔다 — 훅이 걸려 있는 동안 GC 되면 프로세스가 죽는다
        WinUser.LowLevelKeyboardProc proc = new WinUser.LowLevelKeyboardProc() {
            @Override
            public WinDef.LRESULT callback(int nCode, WinDef.WPARAM wParam, WinUser.KBDLLHOOKSTRUCT info) {
                boolean ours = nCode >= 0
                        && (info.flags & LLKHF_INJECTED) != 0
                        && info.dwExtraInfo.longValue() == EXTRA_MARKER;
                if (!ours) {
                    // 사용자의 실제 타자는 건드리지 않는다
                    return User32.INSTANCE.CallNextHookEx(null, nCode, wParam,
                            new WinDef.LPARAM(com.sun.jna.Pointer.nativeValue(info.getPointer())));
                }
                events.add(new Event(wParam.intValue(), info.vkCode, info.flags, info.time));
                // 1 을 돌려주면 이 키는 어떤 창에도 도달하지 않는다 — 테스트가 화면에 자국을 남기지 않는다
                return new WinDef.LRESULT(1);
            }
        };

        WinUser.HHOOK hook = User32.INSTANCE.SetWindowsHookEx(WH_KEYBOARD_LL, proc, instance, 0);
        assertThat(hook).withFailMessage("저수준 키보드 훅을 걸지 못했습니다").isNotNull();
        try {
            Thread injector = new Thread(injection, "sia-live-input");
            injector.setDaemon(true);
            injector.start();
            pump();
            injector.join(PUMP_MS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        } finally {
            User32.INSTANCE.UnhookWindowsHookEx(hook);
        }
        return List.copyOf(events);
    }

    private void pump() {
        WinUser.MSG msg = new WinUser.MSG();
        long deadline = System.currentTimeMillis() + PUMP_MS;
        while (System.currentTimeMillis() < deadline) {
            // 훅 콜백은 이 펌프 안에서 불린다. 기다리는 사이 훅이 시간 초과되지 않도록 쉬지 않고 돈다
            User32.INSTANCE.PeekMessage(msg, null, 0, 0, PM_REMOVE);
        }
    }
}
