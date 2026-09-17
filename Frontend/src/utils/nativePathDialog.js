function isTauriRuntime() {
  return Boolean(window.__TAURI_INTERNALS__ || window.__TAURI__);
}

function invokeCommand() {
  return window.__TAURI_INTERNALS__?.invoke
    || window.__TAURI__?.core?.invoke
    || window.__TAURI__?.invoke;
}

function normalizePath(result) {
  if (result == null || result === false) return null;
  if (Array.isArray(result)) return typeof result[0] === 'string' && result[0] ? result[0] : null;
  if (typeof result === 'string') return result || null;
  if (typeof result === 'object') return result.path || result.filePath || null;
  return null;
}

// Tauri 2 dialog: invoke('plugin:dialog|open', { options }). 웹은 undefined
export async function pickNativeAbsolutePath({ directory = false } = {}) {
  const options = {
    directory,
    multiple: false,
    title: directory ? '열 폴더 선택' : '열 파일 선택',
  };

  const dialogOpen = window.__TAURI__?.dialog?.open;
  if (typeof dialogOpen === 'function') {
    return normalizePath(await dialogOpen(options));
  }

  const invoke = invokeCommand();
  if (typeof invoke !== 'function') return undefined;

  const result = await invoke('plugin:dialog|open', { options });
  if (result == null || result === false) return null;
  const path = normalizePath(result);
  if (typeof path === 'string' && path) return path;

  const error = new Error('TAURI_DIALOG_UNAVAILABLE');
  error.code = 'TAURI_DIALOG_UNAVAILABLE';
  throw error;
}

export { isTauriRuntime };
