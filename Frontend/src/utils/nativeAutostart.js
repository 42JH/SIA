function invokeCommand() {
  return window.__TAURI_INTERNALS__?.invoke
    || window.__TAURI__?.core?.invoke
    || window.__TAURI__?.invoke;
}

export async function syncAutostart(enabled) {
  const invoke = invokeCommand();
  if (typeof invoke !== 'function') return;
  try {
    await invoke('set_autostart', { enabled });
  } catch (err) {
    // OS 등록 실패는 비치명적 — 값은 이미 BE(SQLite)에 저장됐고, 다음 앱 시작 때
    // sync_autostart_from_backend(Rust)가 다시 맞춘다.
    console.warn('[autostart] OS 자동 실행 설정 반영 실패', err);
  }
}
