# -*- coding: utf-8 -*-
"""브라우저 컨텍스트 수신기 — 백엔드 파트의 크롬 확장이 데이터를 꽂는 자리.

크롬 확장(BE 소유)이 현재 탭의 본문·선택 영역·영상 상태를 여기로 POST하면,
에이전트는 스크린샷 대신/과 함께 깨끗한 텍스트 컨텍스트를 쓴다.
확장이 없거나 죽어 있어도 에이전트는 스크린샷 기반으로 정상 동작한다(자동 폴백).

엔드포인트 (127.0.0.1 전용 — 외부 노출 없음):
  POST /context   확장 → 에이전트. 계약은 DOM_브리지_계약.md
  GET  /health    확장 개발 중 연결 확인용
"""
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8765
MAX_BODY = 512 * 1024
TOKEN_FILE = Path(__file__).parent / "dombridge_token.txt"  # 확장이 읽어 헤더로 제시


def _ensure_token():
    """에이전트만 아는 토큰을 로컬 파일에 둔다. 확장(BE)은 이 파일을 읽어
    X-Bridge-Token 헤더로 제시 — 포트를 가로챈 다른 프로세스와 구별하는 최소 방어."""
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    tok = secrets.token_hex(16)
    TOKEN_FILE.write_text(tok, encoding="utf-8")
    return tok


class DomBridge(threading.Thread):
    def __init__(self, port=PORT):
        super().__init__(daemon=True)
        self.port = port
        self.token = _ensure_token()
        self._lock = threading.Lock()
        self._data = None
        self._t = 0.0
        self.error = None

    def context(self, max_age=6.0):
        """max_age초 이내에 갱신된 브라우저 컨텍스트. 없으면 None (→ 스크린샷 폴백)."""
        with self._lock:
            if self._data is not None and time.monotonic() - self._t <= max_age:
                return self._data
        return None

    def run(self):
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            timeout = 5  # 멈춘 연결이 서버를 영구 블록하지 않게 (Chrome 프리커넥트 등)

            def log_message(self, *a):  # 콘솔 소음 방지
                pass

            def _authed(self):
                return self.headers.get("X-Bridge-Token", "") == bridge.token

            def _reply(self, code, obj):
                body = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                # 확장은 /health의 토큰 확인으로 '진짜 에이전트'임을 검증한 뒤에만
                # 페이지 텍스트를 보낸다 (포트 가로채기한 가짜에게 유출 방지)
                if self.path == "/health":
                    self._reply(200, {"ok": self._authed()})
                else:
                    self._reply(404, {"error": "unknown path"})

            def do_POST(self):
                if self.path != "/context":
                    self._reply(404, {"error": "unknown path"})
                    return
                if not self._authed():
                    self._reply(403, {"error": "bad token"})
                    return
                n = int(self.headers.get("Content-Length", 0))
                if n > MAX_BODY:
                    self._reply(413, {"error": "too large"})
                    return
                try:
                    data = json.loads(self.rfile.read(n).decode("utf-8"))
                    assert isinstance(data, dict)
                except Exception:
                    self._reply(400, {"error": "invalid json"})
                    return
                with bridge._lock:
                    bridge._data = data
                    bridge._t = time.monotonic()
                self._reply(200, {"ok": True})

        try:
            ThreadingHTTPServer(("127.0.0.1", self.port), Handler).serve_forever()
        except OSError as e:  # 포트 점유 등 — 브리지 없이도 에이전트는 동작
            self.error = e
            print(f"DOM bridge off (port {self.port}: {e}) - screenshot fallback")
