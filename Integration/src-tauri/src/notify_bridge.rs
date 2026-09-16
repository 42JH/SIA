//! `/ws/fe` 브릿지 — Frontend/src/ws/feSocket.js 와 동일한 프로토콜로 BE에 붙어
//! 알림류 이벤트를 받는다. 인증 없음, 고정 URL(포트 8080), 2초 고정 재연결 —
//! feSocket.js 와 정책을 그대로 맞췄다 (FE와 동시에 붙어도 되는지는 실행해서 확인 중).
//!
//! kind별 판단은 전혀 하지 않고, 받은 {type, data} 봉투를 그대로 overlay 창에
//! emit만 한다 — 실제 표시 로직(토스트 vs 진행상태, 자동 소멸 시간 등)은 전부
//! overlay/index.html의 JS가 담당한다.

use std::sync::Mutex;
use std::time::Duration;

use futures_util::StreamExt;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager};
use tokio_tungstenite::tungstenite::Message;

/// Frontend/src/ws/feSocket.js 의 WS_URL 과 동일. 포트 정책은 아직 TBD (Integration/Agents.md 참고) —
/// BE가 고정 8080이 아니게 되면 여기도 같이 바꿔야 한다.
const WS_URL: &str = "ws://127.0.0.1:8080/ws/fe";
/// feSocket.js 의 RECONNECT_DELAY_MS 와 동일.
const RECONNECT_DELAY: Duration = Duration::from_secs(2);

/// 가장 최근에 받은 `session_state` 이벤트의 data를 들고 있는 앱 상태.
///
/// 문제: 오버레이 창의 JS(`window.__TAURI__.event.listen("sia://notify", ...)`)가
/// 웹뷰 로드를 마치고 리스너를 등록하기 전에, Rust 쪽은 이미 앱 시작과 동시에
/// `/ws/fe`에 붙어서 가장 이른 `session_state`(PASSIVE, 부팅 토스트)를 emit해버릴 수
/// 있다. Tauri의 이벤트는 리스너가 없을 때 emit되면 그냥 유실되고 나중에 재생되지
/// 않는다 — 그래서 "시아가 시작되었습니다" 토스트가 안 뜨는 버그가 발생했다.
///
/// 해결(레디 핸드셰이크): 오버레이 JS가 리스너 등록을 마친 직후
/// `"sia://overlay-ready"`를 emit하고, Rust는 그걸 받으면(`lib.rs`의 setup에서
/// 리스닝) 여기 저장해둔 마지막 `session_state`를 한 번 더 오버레이로 보내준다
/// (`resend_last_session_state`). 리스너 등록 이후에 emit되므로 이번엔 유실되지 않는다.
#[derive(Default)]
pub struct LastSessionState(Mutex<Option<Value>>);

/// BE가 보내는 `{type, data}` 봉투. feSocket.js 의 파싱 규칙과 동일하게, data가
/// 객체가 아니면(배열·누락 등) 무시한다.
#[derive(Debug, Deserialize)]
struct Envelope {
    #[serde(rename = "type")]
    kind: String,
    data: Value,
}

/// 앱 시작 시 한 번 호출 — 백그라운드에서 영구 실행되며, 연결이 끊기면 계속 재시도한다.
pub fn spawn(app: AppHandle) {
    tauri::async_runtime::spawn(async move {
        loop {
            if let Err(err) = run_once(&app).await {
                log::warn!("[notify_bridge] /ws/fe 연결 끊김 또는 실패: {err}");
            }
            tokio::time::sleep(RECONNECT_DELAY).await;
        }
    });
}

async fn run_once(app: &AppHandle) -> Result<(), tokio_tungstenite::tungstenite::Error> {
    let (ws_stream, _) = tokio_tungstenite::connect_async(WS_URL).await?;
    log::info!("[notify_bridge] /ws/fe 연결됨");

    let (_write, mut read) = ws_stream.split();
    while let Some(msg) = read.next().await {
        if let Message::Text(text) = msg? {
            handle_raw(app, &text);
        }
    }
    Ok(())
}

fn handle_raw(app: &AppHandle, text: &str) {
    let envelope: Envelope = match serde_json::from_str(text) {
        Ok(e) => e,
        Err(_) => return, // 파싱 불가 메시지는 조용히 무시 (feSocket.js와 동일)
    };
    if !envelope.data.is_object() {
        return;
    }
    handle_event(app, &envelope.kind, &envelope.data);
}

/// `overlay` 창으로 보내는 이벤트 payload. 오버레이의 `Integration/overlay/index.html`이
/// `window.__TAURI__.event.listen("sia://notify", ...)`로 그대로 받아서 kind별로 그린다 —
/// 여기서는 판단하지 않고 그대로 중계만 한다 (네이티브 토스트는 쓰지 않기로 결정 — 오버레이
/// 창 하나로 통합, Frontend의 기존 팝업 디자인을 그대로 옮겨왔다).
#[derive(Serialize)]
struct OverlayPayload<'a> {
    kind: &'a str,
    data: &'a Value,
}

/// BE에서 온 이벤트를 그대로 오버레이 창에 전달한다. kind별 분기·표시 로직은 전부
/// overlay/index.html 쪽에 있다 (notificationStore.js·TopNotification.jsx·BootToast.jsx를
/// 그대로 포팅함 — 알림/팝업 네이티브 전환 핸드오프 스펙 참고).
///
/// `session_state`는 부팅 직후 유실될 수 있으므로 `LastSessionState`에도 저장해둔다
/// (레디 핸드셰이크용, 위 `LastSessionState` 문서 참고).
fn handle_event(app: &AppHandle, kind: &str, data: &Value) {
    log::info!("[notify_bridge] 수신: {kind} {data}");

    if kind == "session_state" {
        if let Some(state) = app.try_state::<LastSessionState>() {
            *state.0.lock().unwrap() = Some(data.clone());
        }
    }

    emit_to_overlay(app, kind, data);
}

fn emit_to_overlay(app: &AppHandle, kind: &str, data: &Value) {
    let payload = OverlayPayload { kind, data };
    if let Err(err) = app.emit_to("overlay", "sia://notify", &payload) {
        log::warn!("[notify_bridge] 오버레이로 전달 실패: {err}");
    }
}

/// 오버레이 창이 `"sia://overlay-ready"`로 리스너 등록 완료를 알려오면 호출된다.
/// 저장해둔 마지막 `session_state`가 있으면 다시 한번 오버레이로 보낸다 — 이번엔
/// 오버레이 쪽 리스너가 이미 등록된 뒤이므로 유실되지 않는다.
pub fn resend_last_session_state(app: &AppHandle) {
    let Some(state) = app.try_state::<LastSessionState>() else {
        return;
    };
    let last = state.0.lock().unwrap().clone();
    if let Some(data) = last {
        log::info!("[notify_bridge] 오버레이 준비 완료 — 마지막 session_state 재전송");
        emit_to_overlay(app, "session_state", &data);
    }
}
