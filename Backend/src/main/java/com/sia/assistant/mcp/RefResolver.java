package com.sia.assistant.mcp;

import com.sia.assistant.common.BlockedException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.control.window.WindowService;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;
import org.springframework.stereotype.Component;

/**
 * LLM 은 ref 만 다룬다 (win:N / app:key) — hwnd·경로는 이 계층 안쪽에만 있다.
 * 창 스냅샷은 context.get / window.list / window.next / window.prev 가 갱신하고,
 * resolve 시점에 IsWindow 로 생존을 재확인한다 (스냅샷과 실제 화면 사이의 시차 방어).
 */
@Component
public class RefResolver {

    private static final String NOT_FOUND_MESSAGE = "대상을 찾을 수 없습니다. context.get으로 목록을 다시 확인하세요";

    private final WindowService windowService;
    private final AtomicReference<List<WindowService.WindowInfo>> snapshot = new AtomicReference<>(List.of());

    public RefResolver(WindowService windowService) {
        this.windowService = windowService;
    }

    /** 스냅샷 갱신 + LLM 에 보여줄 형태(ref 는 1부터)로 반환. hwnd 는 싣지 않는다. */
    public List<Map<String, Object>> refreshWindows() {
        List<WindowService.WindowInfo> list = List.copyOf(windowService.list());
        snapshot.set(list);
        List<Map<String, Object>> out = new ArrayList<>(list.size());
        for (int i = 0; i < list.size(); i++) {
            WindowService.WindowInfo w = list.get(i);
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("ref", "win:" + (i + 1));
            entry.put("title", w.title());
            entry.put("app", w.app());
            entry.put("state", w.state());
            out.add(entry);
        }
        return out;
    }

    /** "win:N" → hwnd. 스냅샷 범위 밖이거나 창이 이미 죽었으면 REF_NOT_FOUND. */
    public long resolveWindow(String winRef) {
        int n = parseWinRef(winRef);
        List<WindowService.WindowInfo> list = snapshot.get();
        if (n < 1 || n > list.size()) {
            throw notFound();
        }
        long hwnd = list.get(n - 1).hwnd();
        if (!windowService.isAlive(hwnd)) {
            throw notFound();
        }
        return hwnd;
    }

    /** "app:key" → key. 접두사 없는 순수 키도 관용적으로 받는다 (존재 검증은 AppLaunchService 가 한다). */
    public String resolveAppKey(String appRef) {
        if (appRef == null || appRef.isBlank()) {
            throw notFound();
        }
        String key = appRef.trim();
        if (key.startsWith("app:")) {
            key = key.substring("app:".length()).trim();
        }
        if (key.isEmpty()) {
            throw notFound();
        }
        return key;
    }

    /** 현재 스냅샷 원본 (window.next/prev, foreground 매칭용 — LLM 에 내보내지 않는다). */
    public List<WindowService.WindowInfo> current() {
        return snapshot.get();
    }

    /** 현재 스냅샷에서 hwnd 의 ref. 없으면 null. */
    public String refOf(long hwnd) {
        List<WindowService.WindowInfo> list = snapshot.get();
        for (int i = 0; i < list.size(); i++) {
            if (list.get(i).hwnd() == hwnd) {
                return "win:" + (i + 1);
            }
        }
        return null;
    }

    private static int parseWinRef(String winRef) {
        if (winRef == null) {
            throw notFound();
        }
        String s = winRef.trim();
        if (!s.startsWith("win:")) {
            throw notFound();
        }
        try {
            return Integer.parseInt(s.substring("win:".length()).trim());
        } catch (NumberFormatException e) {
            throw notFound();
        }
    }

    private static BlockedException notFound() {
        return new BlockedException(ErrorCode.REF_NOT_FOUND, NOT_FOUND_MESSAGE);
    }
}
