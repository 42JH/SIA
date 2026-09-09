# -*- coding: utf-8 -*-
"""BE 연결 계층 최소판 — runtime.json 읽기 + MCP 클라이언트 (스파이크).

BE 가 기동 시 쓰는 %APPDATA%/SIA/runtime.json 을 읽어 MCP(/mcp)에 접속한다.
프로토콜: MCP Streamable HTTP — initialize → notifications/initialized →
tools/list · tools/call. 응답은 application/json 또는 SSE(text/event-stream)
어느 쪽이든 처리한다. 인증은 Bearer 토큰 + X-Caller.

연결 스파이크 사용법 (BE 서버 기동 후):
  python be_link.py --check                    runtime 읽기 → initialize → 도구 목록
  python be_link.py --call context.get         읽기 도구 호출 (세션 불필요)
  python be_link.py --call app.launch --json "{\"appRef\":\"app:chrome\"}"
                                               S 도구 — 세션 없으면 SESSION_REQUIRED 가
                                               돌아오는 것 자체가 게이트 검증이다
NOTE(한계): WS 채널은 아직 없다(웹소켓 클라이언트는 -58 본작업). 세션을 열 수
없으므로 S 도구는 전부 SESSION_REQUIRED 가 정상이다.
"""
import json
import os
import sys
import threading
import time
import urllib.request
from pathlib import Path

PROTOCOL_VERSION = "2025-11-25"
AGENT_VERSION = "0.4.2"


def read_runtime():
    """BE 접속 정보. 없으면 None — 호출측은 폴백(단독 동작)으로."""
    p = Path(os.environ.get("APPDATA", "")) / "SIA" / "runtime.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class McpClient:
    def __init__(self, port, token, caller="LLM"):
        self.url = f"http://127.0.0.1:{port}/mcp"
        self.token = token
        self.caller = caller
        self.session_id = None
        self._rpc_id = 0

    def _post(self, body):
        """JSON-RPC 한 건 전송 → (응답 객체 또는 None, 응답 헤더)."""
        req = urllib.request.Request(self.url, data=json.dumps(body).encode("utf-8"), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("X-Caller", self.caller)
        if self.session_id:
            req.add_header("Mcp-Session-Id", self.session_id)
        with urllib.request.urlopen(req, timeout=15) as resp:
            ctype = resp.headers.get("Content-Type", "")
            raw = resp.read().decode("utf-8")
            headers = resp.headers
        if not raw.strip():
            return None, headers
        if "text/event-stream" in ctype:  # SSE — data: 줄들에서 JSON-RPC 응답을 찾는다
            for line in raw.splitlines():
                if line.startswith("data:"):
                    obj = json.loads(line[5:].strip())
                    if "id" in obj:
                        return obj, headers
            return None, headers
        return json.loads(raw), headers

    def _rpc(self, method, params=None):
        self._rpc_id += 1
        body = {"jsonrpc": "2.0", "id": self._rpc_id, "method": method, "params": params or {}}
        obj, headers = self._post(body)
        if headers.get("Mcp-Session-Id"):
            self.session_id = headers["Mcp-Session-Id"]
        if obj and "error" in obj:
            raise RuntimeError(f"MCP 오류: {obj['error']}")
        return obj["result"] if obj else None

    def connect(self):
        info = self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION, "capabilities": {},
            "clientInfo": {"name": "sia-agent", "version": "0.4.2"}})
        # initialized 알림 (id 없는 notification)
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return info

    def tools(self):
        return self._rpc("tools/list").get("tools", [])

    def call(self, name, args=None):
        """도구 호출 → (ok, payload). 실패면 payload 는 {code, message}."""
        r = self._rpc("tools/call", {"name": name, "arguments": args or {}})
        if r.get("isError"):
            sc = r.get("structuredContent") or {}
            return False, {"code": sc.get("code", "FAILED"),
                           "message": sc.get("message") or (r.get("content") or [{}])[0].get("text", "")}
        return True, r.get("structuredContent",
                           (r.get("content") or [{}])[0].get("text", ""))


class AgentLink:
    """AI↔BE 연결 계층 — WS(/ws/agent) 이벤트 채널 + MCP(/mcp) 도구 호출을 묶는다.

    BE 미기동·미접속이면 .connected=False 로 남고, 호출측(brain)은 전부 로컬
    폴백으로 돈다 — BE 없이도 오늘처럼 단독 동작한다(전환기 데모 안전망).

    세션 타이머 소유는 BE 다(PROTOCOL §4). BE 가 push 하는 session_state 의
    epoch deadlineMs 를 monotonic 으로 환산해 session_until_mono 에 캐시하므로,
    brain 은 기존 로컬 session_until 과 똑같이 '발화 시작 시각' 기준으로 게이트한다.

    스레드: WS 수신은 백그라운드 _ws_loop 하나. send 는 brain 스레드에서,
    recv 는 이 루프에서 — websockets.sync 는 송/수신 스레드 분리를 허용한다.
    MCP 호출(call)은 brain 스레드에서만 일어난다(urllib 동기).
    """

    def __init__(self):
        self.rt = read_runtime()
        self.mcp = None
        self.ws = None
        self.connected = False          # WS 열림 (MCP 는 lazy)
        self.session_until_mono = 0.0   # BE 세션 마감(모노토닉 환산) — brain 게이트용
        self.be_session_id = None
        self.calib = None               # CalibSession 또는 None (assistant가 주입)
        self._send_lock = threading.Lock()
        self._stop = False
        if self.rt:
            threading.Thread(target=self._ws_loop, daemon=True).start()

    # --- WS 백그라운드 수신 루프 (끊기면 백오프 재접속) ---
    def _ws_loop(self):
        try:
            from websockets.sync.client import connect
        except Exception as e:
            print(f"[BE] websockets 미설치 — WS 비활성(MCP 만 사용): {e}")
            return
        backoff = 1.0
        while not self._stop:
            try:
                url = f"ws://127.0.0.1:{self.rt['port']}/ws/agent"
                with connect(url, open_timeout=4) as ws:
                    self.ws = ws
                    self.connected = True
                    backoff = 1.0
                    self._send({"type": "hello", "data": {"agentVersion": AGENT_VERSION}})
                    print(f"[BE] /ws/agent 연결됨 (port {self.rt['port']})")
                    while not self._stop:
                        self._on_event(ws.recv())  # recv 는 종료 시 예외
            except Exception as e:
                self.connected = False
                self.ws = None
                if self._stop:
                    break
                time.sleep(backoff)
                backoff = min(backoff * 2, 15.0)
                self.rt = read_runtime() or self.rt  # BE 재기동 시 새 포트 반영

    def _on_event(self, raw):
        try:
            msg = json.loads(raw)
        except ValueError:
            return
        t, d = msg.get("type"), msg.get("data") or {}
        if t == "session_state":
            if d.get("state") == "ACTIVE" and d.get("deadlineMs"):
                remaining = d["deadlineMs"] / 1000.0 - time.time()
                self.session_until_mono = time.monotonic() + max(0.0, remaining)
                self.be_session_id = d.get("sessionId")
            else:  # PASSIVE — 만료·종료
                self.session_until_mono = 0.0
                self.be_session_id = None
        elif self.calib and t and t.startswith("calib_"):
            c = self.calib
            if t == "calib_start":         c.on_start(d.get("tempId"))
            elif t == "calib_collect_start": c.on_collect_start(d.get("n"), d.get("x"), d.get("y"))
            elif t == "calib_restart":     c.on_restart(d.get("tempId"))
            elif t == "calib_registered":  c.on_registered(d.get("id"), d.get("active"))
            elif t == "calib_changed":     c.on_changed(d)
            elif t == "calib_cancel":      c.on_cancel(d.get("tempId"))
        # ponytail: hello_ack/recognition_start/settings_changed/wipe 는 로그만.
        # 설정·blob 동기화는 9/11 MVP 합류 후 붙인다(-61). 모르는 type 은 무시(§0).

    def _send(self, obj):
        ws = self.ws
        if not ws:
            return False
        try:
            with self._send_lock:
                ws.send(json.dumps(obj))
            return True
        except Exception:
            self.connected = False
            return False

    # --- brain 이 부르는 API (모두 best-effort — 예외는 폴백으로 흡수) ---
    def renew(self, opening):
        """유효 명령 판정 후에만. opening=True 면 세션 개시, 아니면 연장(MCP session.extend).
        마감시각은 BE 의 session_state push 로 갱신된다.
        ponytail: WS session_renew 는 합의로 제거, 연장은 session.extend 로 통일."""
        if opening:
            # 호출어 경로는 wakeword_detected 만. BE 가 이걸로 세션을 연다(openOnWakeword).
            # session_open{trigger} 은 활성 세션을 WATCHDOG 으로 죽이고 새로 발급하므로
            # 호출어마다 보내면 세션이 매번 교체된다(프로토콜.md: "호출어 경로에서는 보내지 않는다").
            self._send({"type": "wakeword_detected", "data": {}})
        else:
            self.call("session.extend")

    def end(self):
        if self.be_session_id:
            self._send({"type": "session_end",
                        "data": {"sessionId": self.be_session_id, "reason": "STOPPED"}})
        self.session_until_mono = 0.0

    def notice(self, message):
        self._send({"type": "notice", "data": {"message": message}})

    def call(self, tool, args=None):
        """MCP 도구 호출 → (ok, payload). ok 는 True(성공)/False(BE 가 막음·실패)/
        None(BE 접속 불가 → 로컬 폴백 신호). McpClient 는 lazy 연결·재연결."""
        try:
            if self.mcp is None:
                self.mcp = McpClient(self.rt["port"], self.rt["token"])
                self.mcp.connect()
            return self.mcp.call(tool, args or {})
        except Exception as e:
            self.mcp = None  # 다음 호출 때 재접속
            return None, {"code": "NO_BE", "message": str(e)}

    def close(self):
        self._stop = True
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass


def main():
    rt = read_runtime()
    if not rt:
        sys.exit("runtime.json 없음 — BE 서버를 먼저 실행하세요 (%APPDATA%/SIA/runtime.json)")
    print(f"runtime.json: port={rt['port']} pid={rt.get('pid')}")
    c = McpClient(rt["port"], rt["token"])
    t0 = time.monotonic()
    info = c.connect()
    print(f"initialize ok ({time.monotonic() - t0:.2f}s) — server: {info.get('serverInfo')}")
    if "--call" in sys.argv:
        name = sys.argv[sys.argv.index("--call") + 1]
        args = json.loads(sys.argv[sys.argv.index("--json") + 1]) if "--json" in sys.argv else {}
        t0 = time.monotonic()
        ok, payload = c.call(name, args)
        print(f"{name} → {'성공' if ok else '실패'} ({time.monotonic() - t0:.2f}s)")
        print(json.dumps(payload, ensure_ascii=False, indent=1))
    else:
        tools = c.tools()
        print(f"도구 {len(tools)}개:")
        for t in tools:
            print(f"  {t['name']}")


if __name__ == "__main__":
    main()
