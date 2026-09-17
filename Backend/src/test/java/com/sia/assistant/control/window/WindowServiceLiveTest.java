package com.sia.assistant.control.window;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assumptions.assumeThat;

import java.awt.EventQueue;
import java.util.concurrent.atomic.AtomicReference;
import javax.swing.JFrame;
import javax.swing.JTextField;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfSystemProperty;

/**
 * 창 제어가 <b>실제로 반영되는지</b> 확인하는 스모크 테스트 — Win32 반환값은 성공 여부를 알려 주지 않으므로
 * (SetForegroundWindow 는 성공해도 false 를 주고, ShowWindow 는 이전 표시 상태를 준다) 이것으로만 검증된다.
 *
 * <p>대상은 이 테스트가 직접 띄운 창뿐이다. Gradle 테스트 JVM 은 데몬이 띄운 <b>백그라운드 프로세스</b>라
 * 포그라운드 권한이 없다 — 운영 중인 BE 와 같은 조건이고, 그래서 이 테스트가 의미가 있다.
 * 창이 스스로 앞에 와 버리면(포그라운드 앱이 띄운 JVM 등) 측정할 게 없으므로 건너뛴다.
 *
 * <p>포그라운드를 바꾸고 사용자 세션이 필요해 CI 에서는 돌 수 없다. 기본은 비활성이고
 * {@code ./gradlew test -Dsia.live.window=true --tests '*WindowServiceLiveTest'} 로만 켠다.
 */
@EnabledIfSystemProperty(named = "sia.live.window", matches = "true")
class WindowServiceLiveTest {

    private static final long SETTLE_MS = 400;
    /** 포그라운드를 뺏어 갈 남의 프로세스 — 빈 새 창이라 WM_CLOSE 로 확인 없이 닫힌다 */
    private static final String INTRUDER = "notepad";

    private final WindowService windowService = new WindowService();
    private JFrame frame;
    private long hwnd;
    private long original;
    private long intruder;

    @BeforeEach
    void showWindow() throws Exception {
        original = windowService.foregroundHwnd();
        AtomicReference<JFrame> ref = new AtomicReference<>();
        String title = "SIA-LIVE-WINDOW-" + System.nanoTime();
        EventQueue.invokeAndWait(() -> {
            JFrame f = new JFrame(title);
            f.add(new JTextField("live", 12));
            f.pack();
            f.setVisible(true);
            ref.set(f);
        });
        frame = ref.get();
        Thread.sleep(SETTLE_MS);
        hwnd = windowService.list().stream()
                .filter(w -> title.equals(w.title()))
                .mapToLong(WindowService.WindowInfo::hwnd)
                .findFirst()
                .orElse(0L);
        assertThat(hwnd).withFailMessage("테스트 창(%s)을 창 목록에서 찾지 못했습니다", title).isNotZero();
    }

    @AfterEach
    void cleanUp() throws Exception {
        closeIntruder();
        if (frame != null) {
            JFrame toClose = frame;
            EventQueue.invokeAndWait(toClose::dispose);
        }
        if (original != 0L && windowService.isAlive(original)) {
            try {
                windowService.focus(original);
            } catch (RuntimeException ignored) {
                // 사용자가 보던 창으로 되돌리려는 최선의 시도일 뿐 — 실패해도 테스트 결과와 무관하다
            }
        }
    }

    @Test
    @DisplayName("남의 창이 포그라운드를 쥔 상태에서도 창을 실제로 앞으로 가져온다 — SetForegroundWindow 단독으로는 실패하는 자리")
    void focusActuallyRaisesWindow() throws Exception {
        // ★ 우리 창이 스스로 앞에 와 있으면 측정이 무의미하다(테스트 JVM 이 포그라운드 앱의 자식이면 그렇게 된다).
        //   남의 프로세스에 포그라운드를 넘겨 운영 중인 BE 와 같은 조건을 만든다.
        raiseIntruder();
        assumeThat(windowService.foregroundHwnd())
                .withFailMessage("방해 창이 포그라운드를 쥐지 못해 측정할 수 없습니다")
                .isNotEqualTo(hwnd);

        windowService.focus(hwnd);

        assertThat(windowService.foregroundHwnd())
                .withFailMessage("focus 가 예외 없이 끝났는데 창이 앞에 오지 않았습니다 — 반환값만 보고 성공으로 친 것")
                .isEqualTo(hwnd);
    }

    @Test
    @DisplayName("최소화·최대화·복원이 창 상태에 실제로 반영된다")
    void showCommandsChangeState() {
        windowService.minimize(hwnd);
        assertThat(stateOf()).isEqualTo("MINIMIZED");

        windowService.maximize(hwnd);
        assertThat(stateOf()).isEqualTo("MAXIMIZED");

        windowService.restore(hwnd);
        assertThat(stateOf()).isEqualTo("NORMAL");
    }

    @Test
    @DisplayName("이미 그 상태면 조용히 성공한다 — 두 번 최소화해도 실패가 아니다")
    void repeatingSameStateSucceeds() {
        windowService.minimize(hwnd);
        windowService.minimize(hwnd);

        assertThat(stateOf()).isEqualTo("MINIMIZED");
    }

    @Test
    @DisplayName("권한 판정은 보통 창을 관리자 창으로 몰지 않는다 — 몰면 모든 실패가 ELEVATED_WINDOW 로 나간다")
    void elevationProbeIsNotAlwaysTrue() {
        assertThat(WindowService.blockedByElevation(hwnd))
                .withFailMessage("우리 프로세스의 창을 관리자 권한 창으로 판정했습니다 — 토큰 조회가 깨진 것")
                .isFalse();
    }

    /**
     * 포그라운드를 가져갈 남의 프로세스를 띄운다. 창 목록의 app 이름으로 확인한 창만 방해 창으로 삼는다 —
     * 엉뚱한 창(사용자가 보던 창)을 뒤에서 닫아 버리지 않기 위한 조건이다.
     */
    private void raiseIntruder() throws Exception {
        new ProcessBuilder(INTRUDER + ".exe").start();
        Thread.sleep(1500);
        long foreground = windowService.foregroundHwnd();
        boolean isIntruder = windowService.list().stream()
                .anyMatch(w -> w.hwnd() == foreground && INTRUDER.equals(w.app()));
        intruder = isIntruder ? foreground : 0L;
    }

    private void closeIntruder() throws Exception {
        if (intruder == 0L || !windowService.isAlive(intruder)) {
            return;
        }
        // 내용이 없는 새 창이라 WM_CLOSE 로 조용히 닫힌다 — 강제 종료하지 않는다
        windowService.close(intruder);
        Thread.sleep(500);
    }

    private String stateOf() {
        return windowService.list().stream()
                .filter(w -> w.hwnd() == hwnd)
                .map(WindowService.WindowInfo::state)
                .findFirst()
                .orElse("(목록에 없음)");
    }
}
