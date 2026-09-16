use std::path::PathBuf;
use std::sync::Mutex;
use std::time::{Duration, Instant};

use serde::Deserialize;
use tauri::{
    menu::{Menu, MenuItem},
    tray::{MouseButton, TrayIconBuilder, TrayIconEvent},
    AppHandle, Listener, Manager, WindowEvent,
};
use tauri_plugin_shell::{
    process::{CommandChild, CommandEvent},
    ShellExt,
};

mod notify_bridge;

const READY_TIMEOUT: Duration = Duration::from_secs(45);
const POLL_INTERVAL: Duration = Duration::from_millis(500);

/// `%APPDATA%/SIA/runtime.json` 의 형태. Backend(README 기준)가 기동 시 이 파일에
/// `{token, port, pid}`를 쓴다 — AI 도 같은 파일을 읽어 접속한다.
#[derive(Debug, Deserialize, Clone, PartialEq)]
struct RuntimeInfo {
    #[allow(dead_code)]
    token: String,
    port: u16,
    pid: u32,
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
        .manage(SidecarChildren::default())
        .manage(notify_bridge::LastSessionState::default())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

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

            // --- BE -> (준비 확인) -> AI 순서로 sidecar 기동 ---
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

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
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

/// runtime.json이 "이번에 Tauri가 실행한 그 Backend"를 가리키는지 판단한다.
/// 오래된(이전 실행의) runtime.json을 현재 프로세스로 오인하지 않기 위한 대조.
fn runtime_matches_pid(info: &RuntimeInfo, expected_pid: u32) -> bool {
    info.pid == expected_pid
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

/// BE가 준비됐는지 한 번 확인한다: runtime.json 읽기 + PID 대조 + `/api/status` 200 확인.
/// 셋 다 만족하면 포트를 반환한다. TcpStream은 블로킹이라 spawn_blocking으로 돌린다.
async fn probe_backend_ready(expected_pid: u32) -> Option<u16> {
    let info = read_runtime_info()?;
    if !runtime_matches_pid(&info, expected_pid) {
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
async fn wait_for_backend_ready(expected_pid: u32) -> Option<u16> {
    let deadline = Instant::now() + READY_TIMEOUT;
    loop {
        if let Some(port) = probe_backend_ready(expected_pid).await {
            return Some(port);
        }
        if Instant::now() >= deadline {
            return None;
        }
        tokio::time::sleep(POLL_INTERVAL).await;
    }
}

/// BE를 먼저 띄우고, 준비 확인(`wait_for_backend_ready`)이 끝난 뒤에만 AI를 띄운다.
/// 45초 안에 준비되지 않으면 BE를 종료하고 AI는 실행하지 않는다.
fn spawn_sidecars(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        let shell = app.shell();

        let (mut be_rx, be_child) = match shell
            .sidecar("sia-backend")
            .and_then(|cmd| cmd.spawn().map_err(Into::into))
        {
            Ok(pair) => pair,
            Err(err) => {
                log::error!("sia-backend 실행 실패: {err}");
                return;
            }
        };
        let backend_pid = be_child.pid();

        if let Some(state) = app.try_state::<SidecarChildren>() {
            *state.backend.lock().unwrap() = Some(be_child);
        }

        let Some(port) = wait_for_backend_ready(backend_pid).await else {
            log::error!("Backend가 45초 안에 준비되지 않아 종료하고 AI는 실행하지 않는다");
            kill_sidecars(&app);
            return;
        };
        log::info!("Backend 준비 완료 (port {port}) — AI 실행");

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

        tauri::async_runtime::spawn(async move {
            while let Some(event) = be_rx.recv().await {
                if let CommandEvent::Stdout(line) = event {
                    log::info!("[backend] {}", String::from_utf8_lossy(&line));
                }
            }
        });

        while let Some(event) = ai_rx.recv().await {
            if let CommandEvent::Stdout(line) = event {
                log::info!("[ai] {}", String::from_utf8_lossy(&line));
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_valid_runtime_json() {
        let json = r#"{"token":"abc","port":8080,"pid":1234}"#;
        let info = parse_runtime_info(json).expect("should parse");
        assert_eq!(info.port, 8080);
        assert_eq!(info.pid, 1234);
    }

    #[test]
    fn rejects_malformed_runtime_json() {
        assert!(parse_runtime_info("not json").is_none());
        assert!(parse_runtime_info(r#"{"port":8080}"#).is_none()); // pid 없음
    }

    #[test]
    fn pid_must_match_exactly() {
        let info = RuntimeInfo { token: "t".into(), port: 8080, pid: 111 };
        assert!(runtime_matches_pid(&info, 111));
        assert!(!runtime_matches_pid(&info, 222)); // 오래된 runtime.json 오인 방지
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
}
