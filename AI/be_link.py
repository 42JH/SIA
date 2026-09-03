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
import time
import urllib.request
from pathlib import Path

PROTOCOL_VERSION = "2025-11-25"


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
