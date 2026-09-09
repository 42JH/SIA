// /ws/fe 연결 · 재연결 · {type, data} 봉투 파싱을 담당하는 단일 소켓 모듈 (agents.md 3장, 4.3)
// 컴포넌트에서 이 파일을 직접 쓰지 않고, eventBus를 통해서만 구독한다.

const WS_URL = "ws://127.0.0.1:8080/ws/fe";
const RECONNECT_DELAY_MS = 2000;

let socket = null;
let reconnectTimer = null;
const rawListeners = new Set();

function notify(envelope) {
  rawListeners.forEach((fn) => fn(envelope));
}

function connect() {
  socket = new WebSocket(WS_URL);

  socket.onopen = () => {
    notify({ type: "__connection__", data: { status: "open" } });
  };

  socket.onmessage = (event) => {
    let envelope;
    try {
      envelope = JSON.parse(event.data);
    } catch {
      return; // 파싱 불가 메시지는 무시
    }
    // 봉투는 {type, data} 고정, data는 항상 객체 (agents.md 4.1)
    if (!envelope || typeof envelope.type !== "string") return;
    notify(envelope);
  };

  socket.onclose = () => {
    notify({ type: "__connection__", data: { status: "closed" } });
    scheduleReconnect();
  };

  socket.onerror = () => {
    // onclose가 뒤이어 호출되므로 별도 처리하지 않음
  };
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, RECONNECT_DELAY_MS);
}

export function startFeSocket() {
  if (socket) return; // 중복 연결 생성 금지 (agents.md 1장)
  connect();
}

export function sendFeMessage(type, data = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) return false;
  socket.send(JSON.stringify({ type, data }));
  return true;
}

// eventBus 전용 - 컴포넌트에서 직접 호출하지 않음
export function subscribeRaw(fn) {
  rawListeners.add(fn);
  return () => rawListeners.delete(fn);
}
