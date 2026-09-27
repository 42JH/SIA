package com.sia.assistant.control.browser;

import com.sia.assistant.control.com.ComWorker;
import com.sia.assistant.control.window.WindowService;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * 브라우저 확장이 없을 때의 본문 공급원 — 화면 접근성(UIA)으로 브라우저 창의 문서를 읽는다.
 *
 * <p>확장과 같은 품질이 아니다. 확장은 {@code article}/{@code main} 을 먼저 골라 <b>본문만</b> 뽑지만
 * 여기서 얻는 것은 접근성 트리의 텍스트 전체라 메뉴·사이드바·광고 문구가 섞인다. 그래서 호출자는
 * 이 경로로 얻은 결과에 {@code via: "accessibility"} 를 달아 AI 가 품질을 알고 쓰게 한다.
 *
 * <p>대상 창은 <b>포그라운드 창이 브라우저면 그 창</b>, 아니면 Z 순서상 가장 앞의 브라우저 창이다
 * (확장의 "마지막 포커스 창" 의미에 가장 가깝다). 최소화된 창은 접근성 트리가 비어 있어 건너뛴다.
 */
@Service
public class BrowserTextService {

    private static final Logger log = LoggerFactory.getLogger(BrowserTextService.class);

    /** WindowService.appNameOf 가 주는 소문자 실행 파일명(.exe 제거) 기준. */
    private static final Set<String> BROWSERS =
            Set.of("chrome", "msedge", "firefox", "whale", "brave", "opera", "vivaldi");

    /** LLM 컨텍스트 보호 — 확장 경로(DomTextService)와 같은 상한을 쓴다. */
    static final int MAX_TEXT_CHARS = 20000;

    /**
     * UIA 상한. 예열 재시도 2회(600ms + 1500ms 대기)까지 다 타면 3초 남짓이라 여유를 둔다.
     * 정상 경로는 300ms 안쪽이고, 이 상한에 닿는 건 접근성 트리가 끝내 안 켜지는 PC 뿐이다.
     */
    private static final long UIA_TIMEOUT_MS = 4500;

    /** page 가 null 이면 실패고 reason 이 이유다. 둘 중 하나는 항상 채워진다. */
    public record Read(Page page, String reason) {
        public boolean ok() {
            return page != null;
        }
    }

    public record Page(String url, String title, String text, boolean truncated) {
    }

    private final WindowService windowService;
    private final ComWorker comWorker;

    public BrowserTextService(WindowService windowService, ComWorker comWorker) {
        this.windowService = windowService;
        this.comWorker = comWorker;
    }

    public Read read() {
        Long hwnd = browserHwnd();
        if (hwnd == null) {
            return new Read(null, "열려 있는 브라우저 창을 찾지 못했습니다");
        }
        UiaDocumentText.Document doc;
        try {
            doc = comWorker.call("브라우저 본문 읽기", UIA_TIMEOUT_MS, () -> UiaDocumentText.read(hwnd));
        } catch (RuntimeException e) {
            log.warn("접근성으로 브라우저 본문을 읽지 못했습니다: {}", e.toString());
            return new Read(null, "브라우저에서 본문을 읽지 못했습니다");
        }
        if (doc == null) {
            return new Read(null, "브라우저에서 본문을 읽지 못했습니다");
        }
        String text = normalize(doc.text());
        if (text.isEmpty()) {
            return new Read(null, "페이지에서 읽을 본문이 없습니다");
        }
        boolean truncated = text.length() > MAX_TEXT_CHARS;
        return new Read(new Page(doc.url(), doc.title(),
                truncated ? text.substring(0, MAX_TEXT_CHARS) : text, truncated), null);
    }

    /** 포그라운드가 브라우저면 그 창, 아니면 Z 순서상 가장 앞의 (최소화되지 않은) 브라우저 창. */
    private Long browserHwnd() {
        long foreground = windowService.foregroundHwnd();
        List<WindowService.WindowInfo> windows = windowService.list();
        for (WindowService.WindowInfo w : windows) {
            if (w.hwnd() == foreground && isBrowser(w.app())) {
                return foreground;
            }
        }
        for (WindowService.WindowInfo w : windows) {
            if (isBrowser(w.app()) && !"MINIMIZED".equals(w.state())) {
                return w.hwnd();
            }
        }
        return null;
    }

    static boolean isBrowser(String app) {
        return app != null && BROWSERS.contains(app.toLowerCase(Locale.ROOT));
    }

    /**
     * 접근성 트리 텍스트 정리 — 확장의 innerText 정리와 같은 규칙이다.
     * 줄 안의 연속 공백은 하나로, 빈 줄 3개 이상은 2개로 줄이고 양끝을 다듬는다.
     */
    static String normalize(String raw) {
        if (raw == null) {
            return "";
        }
        return raw.replace("\r\n", "\n")
                .replace('\r', '\n')
                .replaceAll("[ \t ]+", " ")
                .replaceAll("\n{3,}", "\n\n")
                .replaceAll("(?m)^ +| +$", "")
                .trim();
    }
}
