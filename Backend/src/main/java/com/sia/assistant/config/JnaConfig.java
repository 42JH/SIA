package com.sia.assistant.config;

import com.sun.jna.platform.win32.BaseTSD;
import com.sun.jna.platform.win32.User32;
import com.sun.jna.win32.W32APIOptions;
import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Configuration;

/**
 * DPI PER_MONITOR_AWARE_V2 선언. 안 하면 150% 배율 모니터에서 좌표가 전부 어긋난다.
 * 실패해도(구버전 Windows) 경고만 남기고 진행한다.
 */
@Configuration
public class JnaConfig {

    private static final Logger log = LoggerFactory.getLogger(JnaConfig.class);

    /** DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4 */
    private static final long PER_MONITOR_AWARE_V2 = -4L;

    private interface User32Dpi extends com.sun.jna.Library {
        User32Dpi INSTANCE = com.sun.jna.Native.load("user32", User32Dpi.class, W32APIOptions.DEFAULT_OPTIONS);

        boolean SetProcessDpiAwarenessContext(BaseTSD.LONG_PTR value);
    }

    @PostConstruct
    void declareDpiAwareness() {
        try {
            boolean ok = User32Dpi.INSTANCE.SetProcessDpiAwarenessContext(new BaseTSD.LONG_PTR(PER_MONITOR_AWARE_V2));
            if (!ok) {
                log.warn("DPI awareness 설정 실패 — 배율 모니터에서 좌표가 어긋날 수 있다");
            }
        } catch (Throwable t) {
            log.warn("DPI awareness 미지원 환경: {}", t.toString());
        }
        // User32 로드를 미리 유발해 첫 도구 호출 지연을 줄인다
        User32.INSTANCE.GetForegroundWindow();
    }
}
