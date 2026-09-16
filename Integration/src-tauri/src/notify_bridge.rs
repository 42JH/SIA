//! `/ws/fe` 브릿지 — Frontend/src/ws/feSocket.js 와 동일한 프로토콜로 BE에 붙어
//! 알림류 이벤트를 받는다. 인증 없음, 고정 URL(포트 8080), 2초 고정 재연결 —
//! feSocket.js 와 정책을 그대로 맞췄다 (FE와 동시에 붙어도 되는지는 실행해서 확인 중).
//!
//! 지금 단계는 뼈대만: 연결·재연결·{type, data} 봉투 파싱까지만 하고, kind별
//! 실제 처리(네이티브 토스트 / 오버레이 창 분기)는 handle_event()에서 다음 단계로 이어간다.

use std::time::Duration;

use futures_util::StreamExt;
use serde::Deserialize;
use serde_json::Value;
use tauri::AppHandle;
use tokio_tungstenite::tungstenite::Message;

/// Frontend/src/ws/feSocket.js 의 WS_URL 과 동일. 포트 정책은 아직 TBD (Integration/Agents.md 참고) —
/// BE가 고정 8080이 아니게 되면 여기도 같이 바꿔야 한다.
const WS_URL: &str = "ws://127.0.0.1:8080/ws/fe";
/// feSocket.js 의 RECONNECT_DELAY_MS 와 동일.
const RECONNECT_DELAY: Duration = Duration::from_secs(2);

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

/// kind별 실제 처리 — 다음 단계(네이티브 토스트 매핑, 오버레이 창 배선)에서 구현.
/// 지금은 수신 확인용 로그만 남긴다.
///
/// 목표 매핑 (알림/팝업 네이티브 전환 설계 확정본):
///   notice/success, unknown_command, summary, tool_result, gesture_result,
///   capture_saved, voice_rejected, error, session_state(boot) → 네이티브 토스트
///   confirm/choices → 네이티브 토스트 (응답 대기 없음 — 음성으로 별도 처리됨)
///   listening, session_countdown → 오버레이 창
fn handle_event(_app: &AppHandle, kind: &str, data: &Value) {
    log::info!("[notify_bridge] 수신: {kind} {data}");
    // TODO: kind → 네이티브 토스트 / 오버레이 창 분기 구현
}
