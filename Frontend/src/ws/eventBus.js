// WS type별 리스너 등록 · 해제 (agents.md 3장, 4.3)
// 컴포넌트 · 스토어는 이 파일을 통해서만 WS 이벤트를 구독한다.

import { subscribeRaw } from "./feSocket";

const handlersByType = new Map(); // type -> Set(fn)

subscribeRaw((envelope) => {
  const { type, data } = envelope;
  const handlers = handlersByType.get(type);
  if (!handlers) return; // 모르는 type은 무시하고 별도 처리하지 않음 (agents.md 4.1)
  handlers.forEach((fn) => fn(data));
});

export function on(type, handler) {
  if (!handlersByType.has(type)) {
    handlersByType.set(type, new Set());
  }
  handlersByType.get(type).add(handler);
  return () => off(type, handler);
}

export function off(type, handler) {
  handlersByType.get(type)?.delete(handler);
}
