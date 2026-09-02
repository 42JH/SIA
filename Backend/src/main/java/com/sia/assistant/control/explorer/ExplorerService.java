package com.sia.assistant.control.explorer;

import com.sia.assistant.common.ApiException;
import com.sia.assistant.common.ErrorCode;
import com.sia.assistant.control.com.ComWorker;
import com.sia.assistant.control.com.LateDispatch;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * explorer.items 의 실체 — 파일 탐색기 창의 폴더·항목(이름/절대 경로/선택 여부)과
 * UIA 화면 좌표(bounds)를 모아 준다. 시선 영역과의 교차 판정은 시선을 소유한 AI 쪽 일이고,
 * BE 는 후보를 좌표와 함께 건네는 데까지만 한다 (다이어그램 02 의 분업 유지).
 */
@Service
public class ExplorerService {

    private static final Logger log = LoggerFactory.getLogger(ExplorerService.class);

    /** LLM 컨텍스트 보호 — 항목이 이보다 많으면 앞에서 자르고 truncated 로 알린다. */
    private static final int MAX_ITEMS = 300;
    private static final long TIMEOUT_MS = 8000;

    private final ComWorker comWorker;

    public ExplorerService(ComWorker comWorker) {
        this.comWorker = comWorker;
    }

    public Map<String, Object> items(long hwnd) {
        return comWorker.call("탐색기 항목 조회", TIMEOUT_MS, () -> itemsOnComThread(hwnd));
    }

    /** ComWorker 스레드 전용. */
    private Map<String, Object> itemsOnComThread(long hwnd) {
        String folder = null;
        List<Map<String, Object>> items = null;
        int total = 0;

        try (LateDispatch shell = new LateDispatch("Shell.Application");
             LateDispatch windows = shell.dispCall("Windows")) {
            int count = windows == null ? 0 : windows.intProp("Count");
            for (int i = 0; i < count && items == null; i++) {
                try (LateDispatch win = windows.dispCall("Item", LateDispatch.intVariant(i))) {
                    if (win == null || win.longProp("HWND") != hwnd) {
                        continue;
                    }
                    try (LateDispatch doc = win.dispProp("Document")) {
                        if (doc == null) {
                            break; // IE/Edge 계열 — 탐색기 아님
                        }
                        try (LateDispatch folderObj = doc.dispProp("Folder")) {
                            if (folderObj == null) {
                                break;
                            }
                            try (LateDispatch self = folderObj.dispProp("Self")) {
                                folder = self == null ? null : self.strProp("Path");
                            }
                            Set<String> selected = selectedPaths(doc);
                            try (LateDispatch folderItems = folderObj.dispCall("Items")) {
                                total = folderItems == null ? 0 : folderItems.intProp("Count");
                                items = collectItems(folderItems, total, selected);
                            }
                        }
                    }
                } catch (RuntimeException e) {
                    // 죽어가는 셸 창의 프로퍼티 조회는 실패할 수 있다 — 다음 창으로
                    log.debug("셸 창 {} 조회 실패: {}", i, e.toString());
                }
            }
        }

        if (items == null) {
            throw new ApiException(ErrorCode.INVALID_REQUEST,
                    "지정한 창은 파일 탐색기 창이 아닙니다. context.get으로 탐색기 창의 ref를 확인하세요");
        }

        // bounds 는 best-effort — UIA 가 막혀도 이름·경로·선택 여부만으로 도구는 성립한다
        Map<String, UiaItemBounds.Rect> bounds = UiaItemBounds.byName(hwnd);
        for (Map<String, Object> item : items) {
            UiaItemBounds.Rect r = bounds.get((String) item.get("name"));
            if (r == null) {
                item.put("bounds", null);
            } else {
                Map<String, Object> b = new LinkedHashMap<>();
                b.put("x", r.x());
                b.put("y", r.y());
                b.put("w", r.w());
                b.put("h", r.h());
                item.put("bounds", b);
            }
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("folder", folder);
        out.put("items", items);
        out.put("count", total);
        out.put("truncated", total > items.size());
        return out;
    }

    private List<Map<String, Object>> collectItems(LateDispatch folderItems, int total, Set<String> selected) {
        List<Map<String, Object>> out = new ArrayList<>();
        if (folderItems == null) {
            return out;
        }
        int n = Math.min(total, MAX_ITEMS);
        for (int i = 0; i < n; i++) {
            try (LateDispatch item = folderItems.dispCall("Item", LateDispatch.intVariant(i))) {
                if (item == null) {
                    continue;
                }
                String name = item.strProp("Name");
                String path = item.strProp("Path");
                if (name == null || path == null || path.isBlank()) {
                    continue;
                }
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("name", name);
                row.put("path", path);
                row.put("selected", selected.contains(path.toLowerCase(Locale.ROOT)));
                out.add(row);
            } catch (RuntimeException e) {
                log.debug("탐색기 항목 {} 조회 실패: {}", i, e.toString());
            }
        }
        return out;
    }

    private Set<String> selectedPaths(LateDispatch doc) {
        Set<String> out = new HashSet<>();
        try (LateDispatch sel = doc.dispCall("SelectedItems")) {
            if (sel == null) {
                return out;
            }
            int count = sel.intProp("Count");
            for (int i = 0; i < count; i++) {
                try (LateDispatch item = sel.dispCall("Item", LateDispatch.intVariant(i))) {
                    if (item == null) {
                        continue;
                    }
                    String path = item.strProp("Path");
                    if (path != null && !path.isBlank()) {
                        out.add(path.toLowerCase(Locale.ROOT));
                    }
                }
            }
        } catch (RuntimeException e) {
            log.debug("선택 항목 조회 실패: {}", e.toString());
        }
        return out;
    }
}
