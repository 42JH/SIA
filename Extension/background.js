// SIA DOM Text Bridge — MV3 서비스 워커.
// BE(/ws/ext)와 WebSocket 을 유지하다가
//  - dom_text_request {requestId} 를 받으면 활성 탭에 추출 스크립트를 주입해 본문을 dom_text 로 돌려주고
//  - browser_open_request {requestId, url} 을 받으면 새 탭으로 그 주소를 열고 browser_open 으로 답한다.
// 모든 메시지는 BE 공통 봉투 {"type": "...", "data": {...}} 를 쓴다.

const WS_URL = "ws://127.0.0.1:8080/ws/ext";
const PING_INTERVAL_MS = 20000; // 20초 — 활동이 있으면 크롬이 서비스 워커를 살려 둔다 (Chrome 116+)
const MAX_TEXT_CHARS = 20000;
const OPEN_LOAD_WAIT_MS = 2500; // 제목을 얻으려 로딩을 기다리는 상한. BE 타임아웃(4초)보다 짧아야 폴백이 겹치지 않는다

let socket = null;
let pingTimer = null;

function connect() {
  if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  try {
    socket = new WebSocket(WS_URL);
  } catch (e) {
    scheduleReconnect();
    return;
  }

  socket.onopen = () => {
    send("hello", { extVersion: chrome.runtime.getManifest().version });
    clearInterval(pingTimer);
    pingTimer = setInterval(() => send("ping", {}), PING_INTERVAL_MS);
  };

  socket.onmessage = (event) => {
    let msg;
    try {
      msg = JSON.parse(event.data);
    } catch (e) {
      return;
    }
    if (msg.type === "dom_text_request") {
      handleRequest(msg.data && msg.data.requestId);
    } else if (msg.type === "browser_open_request") {
      handleOpen(msg.data && msg.data.requestId, msg.data && msg.data.url);
    }
    // pong 등 나머지는 무시
  };

  socket.onclose = () => {
    clearInterval(pingTimer);
    socket = null;
    scheduleReconnect();
  };

  socket.onerror = () => {
    // onclose 가 이어서 온다 — 여기서는 아무것도 하지 않는다
  };
}

function scheduleReconnect() {
  // 서비스 워커가 곧 잠들 수 있으므로 setTimeout 에만 의존하지 않는다 — 알람이 1분마다 connect() 를 다시 부른다
  setTimeout(connect, 3000);
}

function send(type, data) {
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type, data: data || {} }));
  }
}

async function handleRequest(requestId) {
  if (!requestId) {
    return;
  }
  const reply = (data) => send("dom_text", Object.assign({ requestId }, data));
  try {
    const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
    if (!tab || !tab.id || !/^https?:/i.test(tab.url || "")) {
      reply({ available: false, reason: "활성 탭이 웹 페이지가 아닙니다" });
      return;
    }
    const results = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractText,
      args: [MAX_TEXT_CHARS],
    });
    const result = results && results[0] && results[0].result;
    if (!result || !result.text) {
      reply({ available: false, reason: "페이지에서 읽을 본문이 없습니다" });
      return;
    }
    reply({
      available: true,
      url: tab.url,
      title: tab.title || "",
      text: result.text,
      truncated: !!result.truncated,
    });
  } catch (e) {
    // chrome:// · 웹 스토어 · PDF 뷰어 등 주입이 금지된 페이지
    reply({ available: false, reason: "이 페이지에서는 본문을 읽을 수 없습니다" });
  }
}

// browser_open_request {requestId, url} → 새 탭으로 열고 제목까지 얻어 회신한다.
// BE 는 http(s) 만 보내지만 확장 쪽에서도 한 번 더 막는다 — 이 소켓은 루프백이어도 신뢰 경계다.
async function handleOpen(requestId, url) {
  if (!requestId) {
    return;
  }
  const reply = (data) => send("browser_open", Object.assign({ requestId }, data));
  if (!url || !/^https?:\/\//i.test(url)) {
    reply({ ok: false, reason: "http(s) 주소가 아닙니다" });
    return;
  }
  try {
    const tab = await chrome.tabs.create({ url, active: true });
    const title = await waitForTitle(tab.id);
    reply({ ok: true, url, title, tabId: tab.id });
  } catch (e) {
    reply({ ok: false, reason: "탭을 열지 못했습니다" });
  }
}

// 탭 로딩 완료를 최대 OPEN_LOAD_WAIT_MS 까지 기다렸다가 제목을 준다.
// 시간 안에 못 끝내도 실패가 아니다 — 탭은 이미 열려 있으므로 제목만 비운 채 돌려준다.
function waitForTitle(tabId) {
  return new Promise((resolve) => {
    let done = false;
    const finish = (title) => {
      if (done) {
        return;
      }
      done = true;
      chrome.tabs.onUpdated.removeListener(onUpdated);
      clearTimeout(timer);
      resolve(title || "");
    };
    const onUpdated = (id, info, tab) => {
      if (id === tabId && info.status === "complete") {
        finish(tab && tab.title);
      }
    };
    chrome.tabs.onUpdated.addListener(onUpdated);
    const timer = setTimeout(async () => {
      try {
        const tab = await chrome.tabs.get(tabId);
        finish(tab && tab.title);
      } catch (e) {
        finish("");
      }
    }, OPEN_LOAD_WAIT_MS);
  });
}

// 페이지 컨텍스트에서 실행된다 — 기사(article/main) 우선, 없으면 body 전체.
function extractText(maxChars) {
  const root =
    document.querySelector("article") ||
    document.querySelector("main") ||
    document.querySelector("[role=main]") ||
    document.body;
  let text = root && root.innerText ? root.innerText : "";
  text = text
    .replace(/[ \t ]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
  const truncated = text.length > maxChars;
  return { text: truncated ? text.slice(0, maxChars) : text, truncated };
}

// 서비스 워커가 깨어날 때마다 접속을 시도하고, 알람으로 1분마다 재확인한다.
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("sia-reconnect", { periodInMinutes: 1 });
  connect();
});
chrome.runtime.onStartup.addListener(connect);
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "sia-reconnect") {
    connect();
  }
});
chrome.alarms.create("sia-reconnect", { periodInMinutes: 1 });
connect();
