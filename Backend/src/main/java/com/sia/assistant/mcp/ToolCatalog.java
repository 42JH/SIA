package com.sia.assistant.mcp;

import java.util.Collection;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 도구 스펙의 원천 — tool 테이블은 기동 시 ToolCatalogSync 가 여기서 UPSERT 한 투영이다
 * (마이그레이션에 도구 시드는 없다. @McpTool 등록이 여기 없으면 기동을 세운다).
 * description 상수는 @McpTool(description=...) 애너테이션과 이 카탈로그가 같은 문장을 쓰기 위한 것이다
 * (애너테이션 값은 컴파일 타임 상수여야 하므로 여기서 public static final 로 공유한다).
 */
public final class ToolCatalog {

    public record ToolSpec(String name, boolean sessionRequired, boolean confirmRequired, String description) {
    }

    // ------------------------------------------------------------ LLM 용 설명 (한국어 완결 문장)
    public static final String D_CONTEXT_GET =
            "현재 화면 상황을 조회합니다. 컨텍스트 체인, 포그라운드 창, 열린 창 목록(ref 포함), 실행 가능한 앱 목록을 반환합니다. 창이나 앱을 조작하기 전에 먼저 호출해 ref 를 얻으세요.";
    public static final String D_APP_LIST =
            "사용자가 등록한 실행 가능한 앱 목록을 반환합니다. 각 항목의 ref(app:키)를 app.launch 에 그대로 넘기세요.";
    public static final String D_APP_LAUNCH =
            "등록된 앱을 실행합니다. appRef 는 app.list 또는 context.get 이 준 ref(app:키)만 사용할 수 있으며, 파일 경로를 직접 넘길 수 없습니다.";
    public static final String D_BROWSER_SEARCH =
            "기본 브라우저로 검색하거나 주소를 엽니다. query 가 http:// 또는 https:// 로 시작하면 그 주소를, 아니면 구글 검색 결과를 새 탭에 엽니다. "
                    + "반환의 domAvailable 이 true 면 이어서 페이지 본문을 읽을 수 있고, false 면 열어 준 것까지만 확실합니다 — "
                    + "false 일 때는 본문을 읽었다고 말하지 마세요.";
    public static final String D_BROWSER_DOM_TEXT =
            "사용자가 지금 보고 있는 웹페이지의 본문을 읽어 제목 · 주소 · 텍스트를 반환합니다. "
                    + "\"이 페이지 요약해줘\"처럼 화면의 웹 내용을 알아야 답할 수 있을 때 호출하세요. "
                    + "반환의 via 가 extension 이면 본문만 정확히 추출한 것이고, accessibility 면 화면을 읽은 것이라 "
                    + "메뉴 · 사이드바가 섞여 있을 수 있습니다 — 이때는 본문이 아닌 부분을 걸러 읽으세요. "
                    + "본문은 2만 자에서 잘리며 잘렸으면 truncated 가 true 입니다.";
    public static final String D_WINDOW_LIST =
            "현재 열린 창 목록을 새로 조회합니다. 각 창의 ref(win:N), 제목, 앱 이름, 상태(NORMAL|MINIMIZED|MAXIMIZED)를 반환합니다.";
    public static final String D_WINDOW_FOCUS =
            "지정한 창을 앞으로 가져와 포커스를 줍니다. winRef 는 context.get 또는 window.list 가 준 ref(win:N)만 사용하세요.";
    public static final String D_WINDOW_MINIMIZE =
            "지정한 창을 최소화합니다.";
    public static final String D_WINDOW_MAXIMIZE =
            "지정한 창을 최대화합니다.";
    public static final String D_WINDOW_RESTORE =
            "최소화되거나 최대화된 창을 보통 크기로 되돌립니다.";
    public static final String D_WINDOW_RESIZE =
            "지정한 창의 크기와 위치를 프리셋으로 바꿉니다. preset 은 LEFT_HALF, RIGHT_HALF, CENTER 중 하나입니다. "
                    + "최대화·복원은 window.maximize·window.restore 를 쓰세요.";
    public static final String D_WINDOW_CLOSE =
            "지정한 창을 닫습니다. 사용자 확인 게이트를 통과해야 실제로 실행됩니다.";
    public static final String D_WINDOW_NEXT =
            "포그라운드 창 기준으로 다음 창으로 전환합니다.";
    public static final String D_WINDOW_PREV =
            "포그라운드 창 기준으로 이전 창으로 전환합니다.";
    public static final String D_EXPLORER_ITEMS =
            "파일 탐색기 창의 폴더 경로와 항목 목록을 반환합니다. 각 항목은 name, path(절대 경로), selected(선택 여부), "
                    + "bounds(화면 픽셀 사각형 {x,y,w,h}, 모르면 null)를 담습니다. winRef 를 생략하면 포그라운드 창을 봅니다. "
                    + "사용자가 화면의 파일을 가리켜 말하면 이 도구로 후보를 얻어 시선 좌표와 bounds 를 교차해 좁히고, "
                    + "files.delete 에 넘길 절대 경로도 여기서 얻으세요.";
    public static final String D_SCROLL_STEP =
            "포커스된 창을 스크롤합니다. dir 은 up|down|left|right 이고, amount 는 1~10 (생략 시 3)입니다.";
    public static final String D_MEDIA_PLAY_PAUSE =
            "미디어를 재생하거나 일시정지합니다. 포그라운드가 유튜브면 해당 창의 단축키를, 아니면 시스템 미디어 키를 사용합니다.";
    public static final String D_MEDIA_MUTE_TOGGLE =
            "미디어 음소거를 켜거나 끕니다. 포그라운드가 유튜브면 해당 창의 단축키를, 아니면 시스템 음소거 키를 사용합니다.";
    public static final String D_MEDIA_NEXT =
            "다음 트랙 또는 다음 영상으로 넘어갑니다. 포그라운드가 유튜브면 해당 창의 단축키를 사용합니다.";
    public static final String D_MEDIA_PREV =
            "이전 트랙 또는 이전 영상으로 돌아갑니다. 포그라운드가 유튜브면 해당 창의 단축키를 사용합니다.";
    public static final String D_VOLUME_STEP =
            "시스템 볼륨을 한 단계 조절합니다. dir 은 up 또는 down 입니다. 값을 정해 맞출 때는 volume.set 을 쓰세요.";
    public static final String D_VOLUME_SET =
            "시스템 볼륨을 지정한 값으로 맞춥니다. level 은 0~100 이고 작업표시줄 볼륨 슬라이더와 같은 척도입니다. "
                    + "범위를 벗어난 값은 0 또는 100 으로 잘라서 맞춥니다. 음소거 상태에서 0 보다 큰 값을 주면 음소거도 함께 풉니다. "
                    + "실제 반영된 level 과 muted 를 반환하므로 사용자에게 그 값을 그대로 알려 주세요. "
                    + "현재 볼륨은 context.get 의 volume 에 있습니다 — '조금만 줄여줘'처럼 상대적인 요청은 그 값에서 계산해 부르세요.";
    public static final String D_FILES_OPEN =
            "지정한 절대 경로의 파일을 Windows 기본 연결 프로그램으로 엽니다. 열기만 하며 내용을 바꾸지 않습니다. 제스처 매크로의 '파일 실행' 단계가 이 도구를 사용합니다.";
    public static final String D_FILES_DELETE =
            "지정한 파일들을 휴지통으로 이동합니다. 완전 삭제가 아니라 복구 가능한 휴지통 이동입니다. 반드시 사용자에게 확인을 받은 뒤에만 호출하세요.";
    public static final String D_FILES_SAVE =
            "텍스트 내용을 문서 폴더(Documents/SIA)에 파일로 저장합니다. name 은 파일 이름, content 는 저장할 내용입니다.";
    public static final String D_SYSTEM_LOCK =
            "화면을 잠급니다(Windows 잠금 화면). 로그아웃이나 종료가 아니라 세션 잠금이라 작업 내용은 그대로 남습니다.";
    public static final String D_SCREEN_CAPTURE =
            "현재 화면을 캡처해 PNG 파일로 저장합니다. winRef 를 주면 그 창 영역만, 생략하면 전체 화면을 캡처합니다. 저장 위치는 사진 폴더(Pictures/SIA)이고 저장된 파일 경로를 반환합니다. 사용자가 보관할 화면 결과물을 만들 때 사용하세요.";
    public static final String D_SCREEN_CAPTURE_REGION =
            "화면의 일부 영역만 캡처해 PNG 파일로 저장합니다. 영역은 우상단 모서리 (x1, y1)과 좌하단 모서리 (x2, y2) 두 점으로 지정합니다. "
                    + "좌표는 가상 스크린 물리 픽셀이며 explorer.items 의 bounds, 시선 좌표와 같은 좌표계입니다. "
                    + "두 점의 순서가 바뀌어도 두 점을 감싸는 사각형으로 정규화하고, 화면 밖으로 나간 부분은 잘라냅니다. "
                    + "저장 위치는 사진 폴더(Pictures/SIA)이고 저장된 파일 경로와 실제 캡처 크기를 반환합니다. "
                    + "사용자가 화면의 특정 부분만 보관하길 원할 때 사용하세요.";
    public static final String D_SESSION_EXTEND =
            "활성 세션의 만료 시간을 연장합니다. 유효한 명령을 처리한 직후에만 호출하세요.";
    public static final String D_SESSION_CANCEL =
            "활성 세션을 즉시 종료합니다.";
    // 도구 30개 — 이 목록이 tool 테이블의 원천이다
    private static final Map<String, ToolSpec> SPECS = build();

    private static Map<String, ToolSpec> build() {
        Map<String, ToolSpec> m = new LinkedHashMap<>();
        put(m, "context.get",       false, false, D_CONTEXT_GET);
        put(m, "app.list",          false, false, D_APP_LIST);
        put(m, "app.launch",        true,  false, D_APP_LAUNCH);
        put(m, "browser.search",    true,  false, D_BROWSER_SEARCH);
        put(m, "browser.dom_text",  true,  false, D_BROWSER_DOM_TEXT);
        put(m, "window.list",       false, false, D_WINDOW_LIST);
        put(m, "window.focus",      true,  false, D_WINDOW_FOCUS);
        put(m, "window.minimize",   true,  false, D_WINDOW_MINIMIZE);
        put(m, "window.maximize",   true,  false, D_WINDOW_MAXIMIZE);
        put(m, "window.restore",    true,  false, D_WINDOW_RESTORE);
        put(m, "window.resize",     true,  false, D_WINDOW_RESIZE);
        put(m, "window.close",      true,  true,  D_WINDOW_CLOSE);
        put(m, "window.next",       true,  false, D_WINDOW_NEXT);
        put(m, "window.prev",       true,  false, D_WINDOW_PREV);
        put(m, "explorer.items",    false, false, D_EXPLORER_ITEMS);
        put(m, "scroll.step",       true,  false, D_SCROLL_STEP);
        put(m, "media.play_pause",  true,  false, D_MEDIA_PLAY_PAUSE);
        put(m, "media.mute_toggle", true,  false, D_MEDIA_MUTE_TOGGLE);
        put(m, "media.next",        true,  false, D_MEDIA_NEXT);
        put(m, "media.prev",        true,  false, D_MEDIA_PREV);
        put(m, "volume.step",       true,  false, D_VOLUME_STEP);
        put(m, "volume.set",        true,  false, D_VOLUME_SET);
        put(m, "files.open",        true,  false, D_FILES_OPEN);
        put(m, "files.delete",      true,  true,  D_FILES_DELETE);
        put(m, "files.save",        true,  false, D_FILES_SAVE);
        put(m, "system.lock",       true,  false, D_SYSTEM_LOCK);
        put(m, "screen.capture",    true,  false, D_SCREEN_CAPTURE);
        put(m, "screen.capture_region", true, false, D_SCREEN_CAPTURE_REGION);
        put(m, "session.extend",    true,  false, D_SESSION_EXTEND);
        put(m, "session.cancel",    true,  false, D_SESSION_CANCEL);
        return Collections.unmodifiableMap(m);
    }

    private static void put(Map<String, ToolSpec> m, String name, boolean s, boolean c, String description) {
        m.put(name, new ToolSpec(name, s, c, description));
    }

    /** 없으면 null (예외 아님) — ToolGate 가 failed 로 변환한다. */
    public static ToolSpec spec(String name) {
        return name == null ? null : SPECS.get(name);
    }

    public static Collection<ToolSpec> all() {
        return SPECS.values();
    }

    private ToolCatalog() {
    }
}
