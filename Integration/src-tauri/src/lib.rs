use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde::Deserialize;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, TrayIconBuilder, TrayIconEvent},
    AppHandle, Listener, Manager, WindowEvent,
};
use tauri_plugin_autostart::{MacosLauncher, ManagerExt};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

mod notify_bridge;

const READY_TIMEOUT: Duration = Duration::from_secs(45);
const POLL_INTERVAL: Duration = Duration::from_millis(500);

/// `%APPDATA%/SIA/runtime.json` 의 형태. Backend(README 기준)가 기동 시 이 파일에
/// `{token, port, pid, launchId?}`를 쓴다 — AI 도 같은 파일을 읽어 접속한다.
#[derive(Debug, Deserialize, Clone, PartialEq)]
struct RuntimeInfo {
    #[allow(dead_code)]
    token: String,
    port: u16,
    pid: u32,
    #[serde(rename = "launchId")]
    launch_id: Option<String>,
}

/// BE/AI sidecar 자식 프로세스 핸들. 트레이 "종료"에서 확실히 kill 하기 위해
/// Tauri 상태로 들고 있는다 (창을 숨기기만 하는 close-to-hide와는 별개로,
/// 진짜 종료 시엔 이 프로세스들도 같이 내려야 좀비 프로세스가 안 남는다).
#[derive(Default)]
struct SidecarChildren {
    backend: Mutex<Option<CommandChild>>,
    ai: Mutex<Option<CommandChild>>,
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        // 컴퓨터 시작 시 자동 실행. 실제 on/off는 항상 Rust 쪽에서 apply_autostart로만
        // 건드린다 (FE는 "설정값"만 알고, OS 등록은 여기서 한다) — 인자 없음(None)은
        // 자동 실행 시 추가 커맨드라인 인자를 넘기지 않는다는 뜻.
        .plugin(tauri_plugin_autostart::init(MacosLauncher::LaunchAgent, None))
        .manage(SidecarChildren::default())
        .manage(notify_bridge::LastSessionState::default())
        .invoke_handler(tauri::generate_handler![set_autostart])
        .setup(|app| {
            // 사이드카 스폰 실패 등은 release 빌드에서도 원인 파악이 필요해서 항상 켠다
            // (기존엔 debug_assertions 로만 켰었는데, 그러면 release 설치본에서 문제
            // 생겨도 로그가 아예 없어서 진단이 불가능했다). 기본 타겟(LogDir+Stdout+
            // Webview)이라 설치본 기준 %LOCALAPPDATA%\com.sia.desktop\logs\ 에 남는다.
            app.handle().plugin(
                tauri_plugin_log::Builder::default()
                    .level(log::LevelFilter::Info)
                    .build(),
            )?;

            // --- 트레이 아이콘 + 메뉴 ---
            let open_item = MenuItem::with_id(app, "open", "열기", true, None::<&str>)?;
            let quit_item = MenuItem::with_id(app, "quit", "종료", true, None::<&str>)?;
            let tray_menu = Menu::with_items(app, &[&open_item, &quit_item])?;

            TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .menu(&tray_menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "open" => show_main_window(app),
                    "quit" => {
                        kill_sidecars(app);
                        app.exit(0);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        ..
                    } = event
                    {
                        show_main_window(tray.app_handle());
                    }
                })
                .build(app)?;

            // --- BE -> (준비 확인 + 온보딩 여부 판단) -> AI 순서로 sidecar 기동 ---
            // 메인 창은 더 이상 tauri.conf.json에 정적으로 선언돼 있지 않다 — 온보딩이
            // 필요한 경우에만 여기서(spawn_sidecars 내부) 동적으로 생성한다.
            spawn_sidecars(app.handle().clone());

            // --- 오버레이 창: 주 모니터에 맞춰 크기/위치 재설정 + 클릭 무시(순수 표시 전용) ---
            // tauri.conf.json의 1920x1080 @ (0,0)은 그냥 기본값(fallback)이다. 실제로는
            // 항상 "주 모니터"의 실제 크기/위치로 창을 다시 맞춘다 — 안 그러면 모니터
            // 배치에 따라(예: 보조 모니터가 주 모니터 왼쪽에 있어서 주 모니터가
            // x=1920부터 시작하는 경우 등) 오버레이 창이 두 모니터 사이에 걸쳐버리고,
            // CSS의 `#progress { right/bottom }` 앵커가 화면 우하단이 아니라 모니터
            // 경계 쪽에 위치하게 된다. 창을 정확히 주 모니터 영역과 1:1로 맞추면
            // CSS 앵커링만으로 항상 주 모니터 우하단에 뜬다.
            if let Some(overlay) = app.get_webview_window("overlay") {
                match overlay.primary_monitor() {
                    Ok(Some(monitor)) => {
                        let size = *monitor.size();
                        let position = *monitor.position();
                        if let Err(err) = overlay.set_size(tauri::PhysicalSize::new(size.width, size.height)) {
                            log::warn!("[overlay] 주 모니터 크기로 리사이즈 실패: {err}");
                        }
                        if let Err(err) = overlay.set_position(tauri::PhysicalPosition::new(position.x, position.y)) {
                            log::warn!("[overlay] 주 모니터 위치로 이동 실패: {err}");
                        }
                    }
                    Ok(None) => {
                        log::warn!("[overlay] 주 모니터 정보를 가져오지 못함 — tauri.conf.json 기본값(1920x1080 @ 0,0) 사용");
                    }
                    Err(err) => {
                        log::warn!("[overlay] 주 모니터 조회 실패: {err} — tauri.conf.json 기본값 사용");
                    }
                }
                overlay.set_ignore_cursor_events(true)?;
            }

            // --- /ws/fe 알림 브릿지 (하나의 오버레이 창: 토스트 + 진행상태) ---
            notify_bridge::spawn(app.handle().clone());

            // --- 오버레이 "준비 완료" 핸드셰이크 ---
            // 오버레이 창의 JS가 리스너 등록을 마치고 나면 "sia://overlay-ready"를
            // emit한다. 그 전에 notify_bridge가 이미 보낸(그래서 유실됐을 수 있는)
            // 가장 최근 session_state를 이 시점에 한 번 더 보내준다 — 부팅 토스트
            // ("시아가 시작되었습니다")가 항상 뜨도록 하기 위한 조치.
            let app_handle_for_ready = app.handle().clone();
            app.listen("sia://overlay-ready", move |_event| {
                notify_bridge::resend_last_session_state(&app_handle_for_ready);
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            // 메인 창은 X 눌러도 종료가 아니라 숨기기만 한다.
            // 실제 종료는 트레이 메뉴의 "종료"에서만 (그때 sidecar도 같이 kill).
            if window.label() == "main" {
                if let WindowEvent::CloseRequested { api, .. } = event {
                    let _ = window.hide();
                    api.prevent_close();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}

/// 메인 창을 동적으로 생성한다. 예전엔 `tauri.conf.json`에 `main` 창을 정적으로
/// 선언해서 부팅할 때마다 항상 만들었지만, 이제 "온보딩이 필요할 때만 메인 창을
/// 만든다"로 바뀌면서 Rust 코드에서 직접 만들도록 옮겼다 — 그래야 만드는 시점에
/// 어느 경로로 시작할지(`initial_path`) 고를 수 있다.
///
/// `initial_path`가 `None`이면 프론트엔드 기본 라우트(`"/"` → 온보딩 화면)로,
/// `Some("dashboard")`면 대시보드로 바로 진입한다. 이 URL 기반 진입(`WebviewUrl::App`)이
/// 개발 모드(Vite dev 서버, 기본적으로 SPA 폴백 지원)에서는 문제없이 동작하지만,
/// 프로덕션 빌드(`frontendDist` 정적 서빙)에서 `/dashboard` 같은 하위 경로로 바로
/// 진입해도 index.html로 폴백되는지는 이 샌드박스에서 확인 불가 — `npm run tauri build`
/// 결과물로 직접 확인 필요. 만약 안 되면 오버레이에 쓴 것과 같은 "ready 이벤트 +
/// FE navigate()" 방식으로 바꿔야 한다.
fn create_main_window(app: &AppHandle, initial_path: Option<&str>) -> tauri::Result<()> {
    let url = tauri::WebviewUrl::App(PathBuf::from(initial_path.unwrap_or("")));
    tauri::WebviewWindowBuilder::new(app, "main", url)
        .title("SIA")
        .inner_size(1200.0, 800.0)
        .resizable(true)
        .visible(true)
        .build()?;
    Ok(())
}

/// 트레이 "열기"/좌클릭에서 호출한다.
///
/// 메인 창이 이미 있으면(온보딩이 진행 중이었거나, 이전에 이미 만들어둔 상태) 그냥
/// 보여주기만 한다 — 창을 hide만 하고 destroy는 안 하니 SPA 상태가 그대로 보존된다.
///
/// 메인 창이 없으면, 그건 부팅 시점에 온보딩이 이미 끝나 있어서 애초에 만들지
/// 않았다는 뜻이다(`spawn_sidecars`의 온보딩 체크 참고 — 그게 메인 창을 안 만드는
/// 유일한 이유다). 그러니 지금 처음 만드는 거라면 온보딩이 아니라 대시보드로 바로
/// 진입시킨다.
fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    } else if let Err(err) = create_main_window(app, Some("dashboard")) {
        log::error!("[main-window] 트레이에서 메인 창 생성 실패: {err}");
    }
}

fn kill_sidecars(app: &AppHandle) {
    if let Some(state) = app.try_state::<SidecarChildren>() {
        if let Some(child) = state.backend.lock().unwrap().take() {
            let _ = child.kill();
        }
        if let Some(child) = state.ai.lock().unwrap().take() {
            let _ = child.kill();
        }
    }
}

/// `%APPDATA%/SIA/runtime.json` 경로. Windows 전용 앱이라 `%APPDATA%`를 직접 읽는다.
fn runtime_json_path() -> Option<PathBuf> {
    let appdata = std::env::var_os("APPDATA")?;
    Some(PathBuf::from(appdata).join("SIA").join("runtime.json"))
}

fn read_runtime_info() -> Option<RuntimeInfo> {
    let path = runtime_json_path()?;
    let text = std::fs::read_to_string(path).ok()?;
    parse_runtime_info(&text)
}

/// 순수 함수로 분리 — `npm test`(cargo test)에서 파일 시스템 없이 검증한다.
fn parse_runtime_info(text: &str) -> Option<RuntimeInfo> {
    serde_json::from_str::<RuntimeInfo>(text).ok()
}

/// jpackage 런처와 실제 JVM의 PID는 다르므로 이번 실행에 부여한 ID로 대조한다.
fn runtime_matches_launch(info: &RuntimeInfo, expected_launch_id: &str) -> bool {
    info.launch_id.as_deref() == Some(expected_launch_id)
}

fn new_launch_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|elapsed| elapsed.as_nanos())
        .unwrap_or_default();
    format!("{}-{nanos}", std::process::id())
}

fn is_status_ok(http_status: u16) -> bool {
    http_status == 200
}

/// `/api/status`에 최소한의 raw HTTP/1.1 GET을 날리고 상태 코드만 읽는다.
/// 이 프로젝트엔 이미 tokio가 들어있으니, 이거 하나 때문에 reqwest 같은 무거운
/// HTTP 클라이언트를 새로 얹지 않는다 — 로컬 헬스체크 하나에는 과하다.
fn fetch_status_code(port: u16) -> Option<u16> {
    use std::io::{Read, Write};
    use std::net::TcpStream;
    use std::time::Duration;

    let mut stream = TcpStream::connect(("127.0.0.1", port)).ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
    stream.set_write_timeout(Some(Duration::from_secs(2))).ok()?;

    let request = format!(
        "GET /api/status HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    stream.write_all(request.as_bytes()).ok()?;

    let mut buf = [0u8; 64];
    let n = stream.read(&mut buf).ok()?;
    let head = String::from_utf8_lossy(&buf[..n]);
    parse_status_code(&head)
}

/// 응답의 첫 줄("HTTP/1.1 200 OK")에서 상태 코드만 뽑는다. 순수 함수라 테스트하기 쉽다.
fn parse_status_code(response_head: &str) -> Option<u16> {
    response_head
        .lines()
        .next()?
        .split_whitespace()
        .nth(1)?
        .parse()
        .ok()
}

/// `/api/status` 전체 응답 바디를 읽어온다. `fetch_status_code`는 상태 코드(첫 줄)만
/// 필요해서 64바이트만 읽었지만, 여기서는 JSON 바디(activeVoiceId/activeCalibId)가
/// 필요해서 연결이 닫힐 때까지 전부 읽는다 (요청에 `Connection: close`를 실어 보내서
/// BE가 응답 후 연결을 닫아준다는 전제).
fn fetch_status_body(port: u16) -> Option<String> {
    use std::io::{Read, Write};
    use std::net::TcpStream;
    use std::time::Duration;

    let mut stream = TcpStream::connect(("127.0.0.1", port)).ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
    stream.set_write_timeout(Some(Duration::from_secs(2))).ok()?;

    let request = format!(
        "GET /api/status HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    stream.write_all(request.as_bytes()).ok()?;

    let mut buf = Vec::new();
    stream.read_to_end(&mut buf).ok()?;
    let text = String::from_utf8_lossy(&buf).into_owned();
    let (_head, body) = text.split_once("\r\n\r\n")?;
    Some(body.to_string())
}

/// `GET /api/status` 응답 중 온보딩 판단에 필요한 필드만 뽑는다. 나머지 필드
/// (agentConnected 등)는 관심 없어서 구조체에 안 넣었다 — serde는 모르는 필드를
/// 기본적으로 무시하므로 문제 없다.
#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct StatusResponse {
    active_voice_id: Option<i64>,
    active_calib_id: Option<i64>,
}

/// `activeVoiceId`/`activeCalibId`가 둘 다 있어야(= 음성 임베딩 + 시선 보정 모두
/// active 프로필 존재) 온보딩을 마친 것으로 판단한다.
///
/// 온보딩 흐름(`OnboardingFlow.jsx`)이 welcome -> basic(기기 선택) -> 설치앱 스캔 ->
/// 시동어 등록 -> 음성 등록 -> 시선 보정 순 순차 진행이라, 이 둘(음성/시선)만 확인해도
/// 그 앞 단계들이 이미 끝났다고 볼 수 있다.
fn parse_onboarding_done(body: &str) -> bool {
    serde_json::from_str::<StatusResponse>(body)
        .map(|s| s.active_voice_id.is_some() && s.active_calib_id.is_some())
        .unwrap_or(false)
}

/// `GET /api/settings` 전체 응답 바디를 읽어온다. `fetch_status_body`와 동일한 방식 —
/// 로컬 헬스체크/설정조회 하나하나에 reqwest 를 새로 얹지 않는다.
fn fetch_settings_body(port: u16) -> Option<String> {
    use std::io::{Read, Write};
    use std::net::TcpStream;
    use std::time::Duration;

    let mut stream = TcpStream::connect(("127.0.0.1", port)).ok()?;
    stream.set_read_timeout(Some(Duration::from_secs(2))).ok()?;
    stream.set_write_timeout(Some(Duration::from_secs(2))).ok()?;

    let request = format!(
        "GET /api/settings HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
    );
    stream.write_all(request.as_bytes()).ok()?;

    let mut buf = Vec::new();
    stream.read_to_end(&mut buf).ok()?;
    let text = String::from_utf8_lossy(&buf).into_owned();
    let (_head, body) = text.split_once("\r\n\r\n")?;
    Some(body.to_string())
}

/// `GET /api/settings` 응답(`{..., settings: {autoStart, ...}}`)에서 `autoStart`만 뽑는다.
/// 미지의/누락된 키·타입 오류는 전부 `None` — SettingsSchema(BE)가 이미 타입을 보증하지만,
/// 여기선 방어적으로 한 번 더 확인한다(응답이 깨졌을 때 잘못된 값으로 OS 상태를 바꾸지 않기 위해).
fn parse_auto_start(body: &str) -> Option<bool> {
    serde_json::from_str::<serde_json::Value>(body)
        .ok()?
        .get("settings")?
        .get("autoStart")?
        .as_bool()
}

/// OS 자동 실행 등록을 `enabled`에 맞춘다. 이미 그 상태면 아무 것도 안 한다(불필요한
/// 레지스트리 쓰기 방지). 플러그인 API가 실패해도(권한 문제 등) 앱 자체는 계속 돈다 —
/// 자동 실행은 부가 기능이라 이것 때문에 앱을 막을 이유가 없다.
fn apply_autostart(app: &AppHandle, enabled: bool) {
    let manager = app.autolaunch();
    if let Ok(current) = manager.is_enabled() {
        if current == enabled {
            return;
        }
    }
    let result = if enabled { manager.enable() } else { manager.disable() };
    match result {
        Ok(()) => log::info!("[autostart] {} 완료", if enabled { "활성화" } else { "비활성화" }),
        Err(err) => log::error!("[autostart] {} 실패: {err}", if enabled { "활성화" } else { "비활성화" }),
    }
}

/// 부팅 시 1회 — BE 의 저장된 설정을 읽어 OS 자동 실행 상태를 맞춘다.
async fn sync_autostart_from_backend(app: &AppHandle, port: u16) {
    let Some(body) = tokio::task::spawn_blocking(move || fetch_settings_body(port))
        .await
        .ok()
        .flatten()
    else {
        log::warn!("[autostart] /api/settings 조회 실패 — 동기화 생략(기존 OS 상태 유지)");
        return;
    };
    let Some(enabled) = parse_auto_start(&body) else {
        log::warn!("[autostart] 응답에서 autoStart 를 읽지 못함 — 동기화 생략");
        return;
    };
    apply_autostart(app, enabled);
}

/// FE 의 자동 실행 토글에서 직접 호출한다. BE PUT(/api/settings)이 SQLite 에 값을
/// 저장한 "직후"에 FE 가 이걸 불러 OS 등록을 즉시 맞춘다 — BE 는 값을 들고 있을 뿐,
/// 실제 OS 등록/해제는 데스크톱 셸(Tauri) 만 할 수 있어서 이렇게 나뉜다.
#[tauri::command]
fn set_autostart(app: AppHandle, enabled: bool) {
    apply_autostart(&app, enabled);
}

/// BE가 준비됐는지 한 번 확인한다: runtime.json 읽기 + 실행 ID 대조 + `/api/status` 200 확인.
/// 셋 다 만족하면 포트를 반환한다. TcpStream은 블로킹이라 spawn_blocking으로 돌린다.
async fn probe_backend_ready(expected_launch_id: &str) -> Option<u16> {
    let info = read_runtime_info()?;
    if !runtime_matches_launch(&info, expected_launch_id) {
        return None;
    }

    let port = info.port;
    let status = tokio::task::spawn_blocking(move || fetch_status_code(port))
        .await
        .ok()??;

    if is_status_ok(status) {
        Some(port)
    } else {
        None
    }
}

/// 45초 동안 0.5초 간격으로 `probe_backend_ready`를 반복한다.
async fn wait_for_backend_ready(expected_launch_id: &str) -> Option<u16> {
    let deadline = Instant::now() + READY_TIMEOUT;
    loop {
        if let Some(port) = probe_backend_ready(expected_launch_id).await {
            return Some(port);
        }
        if Instant::now() >= deadline {
            return None;
        }
        tokio::time::sleep(POLL_INTERVAL).await;
    }
}

/// BE를 먼저 띄우고, 준비 확인(`wait_for_backend_ready`)이 끝난 뒤 온보딩 여부를
/// 판단해서 필요하면 메인 창을 만들고, 그 다음 AI를 띄운다. 45초 안에 BE가 준비되지
/// 않으면 BE를 종료하고 AI는 실행하지 않는다.
fn spawn_sidecars(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        let shell = app.shell();
        let launch_id = new_launch_id();

        // 진단용 임시 로그 — os error 2(파일 없음) 원인 확인을 위해 Tauri가 실제로 어느
        // 경로를 기준으로 사이드카를 찾는지 남긴다. 원인 확인되면 지워도 된다.
        log::info!("current_exe = {:?}", std::env::current_exe());
        if let Ok(exe) = std::env::current_exe() {
            if let Some(dir) = exe.parent() {
                let candidate = dir.join("sia-backend.exe");
                log::info!("sidecar 후보 경로 = {:?}, exists = {}", candidate, candidate.exists());
            }
        }

        let (mut be_rx, be_child) = match shell
            .sidecar("sia-backend")
            .map(|cmd| cmd.env("SIA_LAUNCH_ID", launch_id.as_str()))
            .and_then(|cmd| cmd.spawn().map_err(Into::into))
        {
            Ok(pair) => pair,
            Err(err) => {
                log::error!("sia-backend 실행 실패: {err:?}");
                return;
            }
        };
        log::info!("Backend 런처 PID = {}", be_child.pid());

        if let Some(state) = app.try_state::<SidecarChildren>() {
            *state.backend.lock().unwrap() = Some(be_child);
        }

        tauri::async_runtime::spawn(async move {
            while let Some(event) = be_rx.recv().await {
                match event {
                    CommandEvent::Stdout(line) => log::info!("[backend] {}", String::from_utf8_lossy(&line)),
                    CommandEvent::Stderr(line) => log::error!("[backend] {}", String::from_utf8_lossy(&line)),
                    CommandEvent::Error(err) => log::error!("[backend] 출력 수신 실패: {err}"),
                    CommandEvent::Terminated(status) => log::warn!("[backend] 종료: {status:?}"),
                    _ => {}
                }
            }
        });

        let Some(port) = wait_for_backend_ready(&launch_id).await else {
            log::error!("Backend가 45초 안에 준비되지 않아 종료하고 AI는 실행하지 않는다");
            kill_sidecars(&app);
            return;
        };
        log::info!("Backend 준비 완료 (port {port}) — AI 실행");

        // --- BE(SQLite app_settings.autoStart)와 OS 자동 실행 등록 상태 동기화 ---
        // FE 토글이 바뀔 때는 set_autostart 커맨드가 즉시 반영하지만, 그 둘이
        // 어긋날 수 있는 경우(레지스트리 키를 수동으로 지웠다거나, 이 기능이 없던
        // 옛 빌드로 켠 채 저장된 DB 등)를 매 부팅마다 여기서 교정한다.
        sync_autostart_from_backend(&app, port).await;

        // --- 온보딩 필요 여부에 따라 메인 창 생성 여부 결정 ---
        // 이미 온보딩을 마쳤으면(activeVoiceId/activeCalibId 둘 다 있으면) 메인 창을
        // 아예 만들지 않는다 — 트레이 아이콘 + 오버레이(부트 토스트)만 뜨고, 그 외엔
        // 아무 것도 자동으로 열리지 않는다. 나중에 사용자가 트레이 "열기"를 누르면
        // 그때 `show_main_window`가 대시보드로 바로 만든다. 온보딩이 안 끝났으면
        // 지금 바로 메인 창을 만들어 온보딩 화면을 띄운다.
        let onboarded = tokio::task::spawn_blocking(move || fetch_status_body(port))
            .await
            .ok()
            .flatten()
            .map(|body| parse_onboarding_done(&body))
            .unwrap_or(false);

        if onboarded {
            log::info!("[main-window] 온보딩 완료 상태 — 부팅 시 메인 창 생성 생략 (부트 토스트만)");
        } else {
            log::info!("[main-window] 온보딩 필요 — 메인 창을 온보딩 화면으로 생성");
            if let Err(err) = create_main_window(&app, None) {
                log::error!("[main-window] 생성 실패: {err}");
            }
        }

        let (mut ai_rx, ai_child) = match shell
            .sidecar("sia-ai")
            .and_then(|cmd| cmd.spawn().map_err(Into::into))
        {
            Ok(pair) => pair,
            Err(err) => {
                log::error!("sia-ai 실행 실패: {err}");
                return;
            }
        };

        if let Some(state) = app.try_state::<SidecarChildren>() {
            *state.ai.lock().unwrap() = Some(ai_child);
        }

        while let Some(event) = ai_rx.recv().await {
            match event {
                CommandEvent::Stdout(line) => log::info!("[ai] {}", String::from_utf8_lossy(&line)),
                CommandEvent::Stderr(line) => log::error!("[ai] {}", String::from_utf8_lossy(&line)),
                CommandEvent::Error(err) => log::error!("[ai] 출력 수신 실패: {err}"),
                CommandEvent::Terminated(status) => log::warn!("[ai] 종료: {status:?}"),
                _ => {}
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_valid_runtime_json() {
        let json = r#"{"token":"abc","port":8080,"pid":1234,"launchId":"launch-1"}"#;
        let info = parse_runtime_info(json).expect("should parse");
        assert_eq!(info.port, 8080);
        assert_eq!(info.pid, 1234);
        assert_eq!(info.launch_id.as_deref(), Some("launch-1"));
    }

    #[test]
    fn rejects_malformed_runtime_json() {
        assert!(parse_runtime_info("not json").is_none());
        assert!(parse_runtime_info(r#"{"port":8080}"#).is_none()); // pid 없음
    }

    #[test]
    fn launch_id_must_match_exactly() {
        let info = RuntimeInfo { token: "t".into(), port: 8080, pid: 111, launch_id: Some("current".into()) };
        assert!(runtime_matches_launch(&info, "current"));
        assert!(!runtime_matches_launch(&info, "previous"));
        let stale = RuntimeInfo { launch_id: None, ..info };
        assert!(!runtime_matches_launch(&stale, "current"));
    }

    #[test]
    fn only_http_200_counts_as_ready() {
        assert!(is_status_ok(200));
        assert!(!is_status_ok(404));
        assert!(!is_status_ok(500));
        assert!(!is_status_ok(0));
    }

    #[test]
    fn parses_status_code_from_response_head() {
        assert_eq!(parse_status_code("HTTP/1.1 200 OK\r\nContent-Length: 0"), Some(200));
        assert_eq!(parse_status_code("HTTP/1.1 404 Not Found"), Some(404));
        assert_eq!(parse_status_code(""), None);
        assert_eq!(parse_status_code("garbage"), None);
    }

    #[test]
    fn parses_auto_start_from_settings_response() {
        let body = r#"{"version":3,"settings":{"autoStart":true,"wakeWord":"시아야"}}"#;
        assert_eq!(parse_auto_start(body), Some(true));
    }

    #[test]
    fn parse_auto_start_handles_missing_or_malformed() {
        assert_eq!(parse_auto_start(r#"{"settings":{}}"#), None); // 키 없음
        assert_eq!(parse_auto_start(r#"{"settings":{"autoStart":"yes"}}"#), None); // 타입 오류
        assert_eq!(parse_auto_start(r#"{}"#), None); // settings 자체가 없음
        assert_eq!(parse_auto_start("not json"), None);
    }

    #[test]
    fn onboarding_done_needs_both_voice_and_calib() {
        assert!(parse_onboarding_done(r#"{"activeVoiceId":1,"activeCalibId":2}"#));
        assert!(!parse_onboarding_done(r#"{"activeVoiceId":1,"activeCalibId":null}"#));
        assert!(!parse_onboarding_done(r#"{"activeVoiceId":null,"activeCalibId":2}"#));
        assert!(!parse_onboarding_done(r#"{"activeVoiceId":null,"activeCalibId":null}"#));
        assert!(!parse_onboarding_done("not json"));
        assert!(!parse_onboarding_done("{}"));
    }
}
