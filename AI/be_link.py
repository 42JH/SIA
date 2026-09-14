# -*- coding: utf-8 -*-
"""BE 연결 계층 — runtime.json 읽기, WS(/ws/agent) 이벤트 채널, MCP(/mcp) 도구 호출, AI 용 REST 몇 개.

BE 가 기동 시 쓰는 %APPDATA%/SIA/runtime.json 에서 포트·토큰을 읽는다. 파일이 없으면 BE 없이 단독으로 돈다.
- WS: 백그라운드 스레드가 /ws/agent 에 붙어 hello 를 보내고, BE 이벤트(session_state · voice_* · calib_* …)를
  받아 각 담당(brain · CalibSession · VoiceSession · WakeEnroll)에 넘긴다. 끊기면 잠시 기다렸다 다시 붙는다.
- MCP: Streamable HTTP — initialize → notifications/initialized → tools/list · tools/call. 응답은
  application/json 또는 SSE(text/event-stream) 어느 쪽이든 처리한다. 인증은 Bearer 토큰 + X-Caller.
- REST: 제스처 템플릿 npz 업/다운로드, 사용 통계 배치 전송.

단독 점검 (BE 서버 기동 후, MCP 만):
  python be_link.py --check                    runtime 읽기 → initialize → 도구 목록
  python be_link.py --call context.get         읽기 도구 호출 (세션 불필요)
  python be_link.py --call app.launch --json "{\"appRef\":\"app:chrome\"}"
                                               세션이 필요한 도구 — 세션 없으면 SESSION_REQUIRED 가 정상
"""
import json
import os
import sys
import threading
import time
import urllib.request
import uuid
from collections import deque
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

    def __init__(self, voice_sync=None, wake_store=None):
        self.rt = read_runtime()
        self.mcp = None
        self.ws = None
        self.connected = False          # WS 열림 (MCP 는 lazy)
        self.session_until_mono = 0.0   # BE 세션 마감(모노토닉 환산) — brain 게이트용
        self.be_session_id = None
        self._session_condition = threading.Condition()
        self.calib = None               # CalibSession 또는 None (assistant가 주입)
        self._events = deque(maxlen=256)
        self._event_lock = threading.Lock()
        self._usage = []
        self._usage_lock = threading.Lock()
        self._sample_condition = threading.Condition()
        self._sample_queue = deque(maxlen=1)
        self._sample_worker = None
        self._sample_closed = False
        self.gesture_ready = False
        self.voice = None               # VoiceSession 또는 None (assistant가 주입) — 화자 등록(65)
        self.voice_sync = voice_sync    # WS 연결 전에 주입해 부팅 직후 활성 참조도 놓치지 않는다.
        if voice_sync is not None:
            voice_sync.link = self
        self.wake_store = wake_store    # WakeTemplateStore — 호출어 개인화 템플릿(전역 blob:wakeword)
        if wake_store is not None:
            wake_store.link = self
        self.wake = None                # WakeEnroll 또는 None (assistant가 주입) — 온보딩 이름 불러보기(206)
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
                    self.gesture_ready = False
                    backoff = 1.0
                    self._send({"type": "hello", "data": {"agentVersion": AGENT_VERSION}})
                    print(f"[BE] /ws/agent 연결됨 (port {self.rt['port']})")
                    while not self._stop:
                        self._on_event(ws.recv())  # recv 는 종료 시 예외
            except Exception as e:
                self.connected = False
                self.gesture_ready = False
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
        if not isinstance(msg, dict):
            return
        t, d = msg.get("type"), msg.get("data") or {}
        if not isinstance(d, dict):
            return
        if self.voice_sync is not None:
            if t == "voice_changed" and isinstance(msg.get("data"), dict):
                self.voice_sync.on_changed(msg["data"])
            elif t in ("hello_ack", "recognition_start", "settings_changed"):
                blobs = d.get("blobs")
                if isinstance(blobs, dict) and "voice" in blobs:
                    self.voice_sync.on_changed(blobs["voice"])
        if self.wake_store is not None and t in ("hello_ack", "recognition_start", "settings_changed"):
            # 호출어 설정을 먼저 적용한다. 다운로드 시작 뒤 설정이 바뀌면 받은 파일이 폐기된다.
            self.wake_store.on_settings(d.get("settings"))   # settings.wakeWord — 호출어 문자열 자체
            blobs = d.get("blobs")
            if isinstance(blobs, dict) and "wakeword" in blobs:
                self.wake_store.on_blob(blobs["wakeword"])   # 전역 호출어 템플릿 참조 (sha256 또는 null)
        if self.calib is not None and t in ("hello_ack", "recognition_start", "settings_changed"):
            blobs = d.get("blobs")  # 시작·재접속·설정변경 시 활성 보정 참조를 로컬과 맞춘다(-161)
            self.calib.on_blob_ref(blobs.get("calib") if isinstance(blobs, dict) else None)
        if t == "session_state":
            with self._session_condition:
                if d.get("state") == "ACTIVE" and d.get("deadlineMs"):
                    remaining = d["deadlineMs"] / 1000.0 - time.time()
                    self.session_until_mono = time.monotonic() + max(0.0, remaining)
                    self.be_session_id = d.get("sessionId")
                else:  # PASSIVE — 만료·종료
                    self.session_until_mono = 0.0
                    self.be_session_id = None
                self._session_condition.notify_all()
        elif self.calib and t and t.startswith("calib_"):
            c = self.calib
            if t == "calib_start":         c.on_start(d.get("tempId"))
            elif t == "calib_collect_start": c.on_collect_start(d.get("n"), d.get("x"), d.get("y"))
            elif t == "calib_restart":     c.on_restart(d.get("tempId"))
            elif t == "calib_registered":  c.on_registered(d.get("id"), d.get("active"))
            elif t == "calib_changed":     c.on_changed(d)
            elif t == "calib_cancel":      c.on_cancel(d.get("tempId"))
        elif t == "wakeword_enroll_start" and self.wake:
            self.wake.on_start()
        # 온보딩 "명령 문장 말하기"(command_*) 단계는 폐기됐다(229) — 그 낭독 5문장이 곧 위 voice_* 등록이다
        # 마이크·제스처 설정은 메인 루프, 활성 보이스 참조는 위 동기화 워커로 넘긴다.
        # NOTE(한계): wipe 수신은 아직 처리하지 않는다. 모르는 type은 무시한다(프로토콜 §1.5).

        # Calibration events are handled above. Gesture and voice registration events are consumed by
        # assistant.py on its main camera loop, not the WebSocket worker thread.
        if t == "recognition_start":
            self.gesture_ready = True
        if t in {"hello_ack", "recognition_start", "settings_changed", "gesture_toggled",
                 "gesture_registered", "gesture_renamed", "gesture_removed", "gesture_result",
                 "reg_mode_start", "reg_finish", "model_load",
                 "voice_reg_start", "voice_collect", "voice_finalize", "voice_reg_cancel", "voice_registered",
                 "cam_preview_start", "cam_preview_stop"}:
            with self._event_lock:
                self._events.append((t, d))

    def take_events(self):
        """BE 이벤트를 메인 루프에서 순서대로 소비한다."""
        with self._event_lock:
            items = list(self._events)
            self._events.clear()
        return items

    def send_event(self, event_type, data=None):
        return self._send({"type": event_type, "data": data or {}})

    def _agent_request(self, path, method="GET", payload=None, headers=None):
        if not self.rt:
            raise RuntimeError("BE runtime.json이 없습니다")
        data = payload if isinstance(payload, (bytes, bytearray)) else (
            json.dumps(payload).encode("utf-8") if payload is not None else None)
        req = urllib.request.Request(f"http://127.0.0.1:{self.rt['port']}{path}",
                                     data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.rt['token']}")
        req.add_header("X-Caller", "AI")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        return urllib.request.urlopen(req, timeout=15)

    def get_gesture_npz(self, gesture_id, etag=None):
        headers = {"Accept": "application/octet-stream"}
        if etag:
            headers["If-None-Match"] = f'"{etag}"'
        try:
            with self._agent_request(f"/api/agent/gestures/{gesture_id}/npz", headers=headers) as response:
                digest = response.headers.get("ETag", "").strip('"') or None
                return response.read(), digest
        except urllib.error.HTTPError as e:
            if e.code == 304:
                return None, etag
            raise

    def get_voice_npz(self):
        """해시가 다른 파일만 호출측에서 요청한다 — 조건부 GET 없이 누락된 캐시도 복구한다."""
        with self._agent_request("/api/agent/voices/active/npz",
                                 headers={"Accept": "application/octet-stream"}) as response:
            return response.read()

    def get_blob_npz(self, name):
        """이름에 해당하는 NPZ를 받는다. 다운로드 여부는 호출부에서 해시를 비교해 결정한다."""
        with self._agent_request(f"/api/agent/blobs/{name}",
                                 headers={"Accept": "application/octet-stream"}) as response:
            return response.read()

    def put_active_voice_sample(self, wav):
        with self._agent_request("/api/agent/voices/active/sample", method="PUT", payload=wav,
                                 headers={"Content-Type": "audio/wav"}) as response:
            return response.status

    def queue_active_voice_sample(self, wav, profile_ref, generation, is_current):
        """화자 인증을 막지 않고 전용 워커로 보내되, 대기 샘플은 최신 한 건만 유지한다."""
        with self._sample_condition:
            if self._sample_closed:
                return False
            if self._sample_worker is None:
                try:
                    worker = threading.Thread(target=self._run_active_voice_samples, daemon=True)
                    worker.start()
                except Exception as exc:
                    print(f"[활성 보이스 샘플] 워커 시작 실패 error={type(exc).__name__}: {exc} bytes={len(wav)}")
                    return False
                self._sample_worker = worker
            self._sample_queue.append((wav, profile_ref, generation, is_current))
            self._sample_condition.notify()
        return True

    def _run_active_voice_samples(self):
        while True:
            with self._sample_condition:
                self._sample_condition.wait_for(lambda: self._sample_closed or self._sample_queue)
                if self._sample_closed:
                    return
                wav, profile_ref, generation, is_current = self._sample_queue.popleft()
            size = len(wav)
            try:
                if not is_current(profile_ref, generation):
                    print(f"[활성 보이스 샘플] 이전 입력 폐기 profileId={profile_ref[0]} bytes={size}")
                    continue
                with self._sample_condition:
                    if self._sample_closed:
                        return
                status = self.put_active_voice_sample(wav)
                print(f"[활성 보이스 샘플] 전송 완료 status={status} bytes={size}")
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    print(f"[활성 보이스 샘플] 로컬 프로필과 서버 활성 보이스 상태 불일치 "
                          f"profileId={profile_ref[0]} status=404 bytes={size}")
                else:
                    print(f"[활성 보이스 샘플] 전송 실패 status={exc.code} bytes={size}")
            except Exception as exc:
                print(f"[활성 보이스 샘플] 전송 실패 error={type(exc).__name__}: {exc} bytes={size}")

    def put_gesture_npz(self, temp_id, payload):
        with self._agent_request(f"/api/agent/gestures/{temp_id}/npz", method="PUT",
                                 payload=payload,
                                 headers={"Content-Type": "application/octet-stream"}):
            return True

    def post_usage_events(self, events):
        if not events:
            return None
        with self._agent_request("/api/agent/events", method="POST", payload={"events": events},
                                 headers={"Content-Type": "application/json"}) as response:
            return json.loads(response.read().decode("utf-8"))

    def queue_usage(self, kind, **fields):
        event = {key: value for key, value in fields.items() if value is not None}
        event.update(eventUid=str(uuid.uuid4()), kind=kind)
        with self._usage_lock:
            self._usage.append(event)

    def flush_usage(self):
        with self._usage_lock:
            batch, self._usage = self._usage, []
        if not batch:
            return
        try:
            result = self.post_usage_events(batch)
            print(f"[BE] 사용 통계 전송 count={len(batch)} "
                  f"accepted={result.get('accepted')} duplicates={result.get('duplicates')} "
                  f"rejected={result.get('rejected')}")
        except Exception as exc:
            print(f"[BE] 사용 통계 전송 실패 count={len(batch)} — 배치 폐기(재시도 없음): {exc}")

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
    def wake_detected(self):
        """호출어 감지 → BE. FE 'listening' 중계 + 활성 세션 없으면 개시(openOnWakeword).
        활성 세션 중 재수신은 BE 가 무시하므로 LLM 뒤 폴백 발신과 겹쳐도 무해."""
        return self._send({"type": "wakeword_detected", "data": {}})

    def voice_rejected(self):
        """화자 게이트 거부 → BE. BE 가 FE 에 voice_rejected{message} 로 중계(문구는 BE 소유).
        판정할 만큼 유성이 긴 발화에서만 부른다 — 짧은 호출어 거부에서 쏘면 본인 호출마다 문구가 뜬다."""
        self._send({"type": "voice_rejected", "data": {}})

    def renew(self, opening):
        """유효 명령 판정 후에만. opening=True 면 세션 개시, 아니면 연장(MCP session.extend).
        마감시각은 BE 의 session_state push 로 갱신된다.
        WS session_renew 는 쓰지 않는다 — 같은 동작인 MCP session.extend 하나로 통일했다(프로토콜 §2)."""
        if opening:
            # 호출어 경로는 wakeword_detected 만. session_open{trigger} 은 활성 세션을 WATCHDOG 으로 죽이고
            # 새로 발급하므로 호출어마다 보내면 세션이 매번 교체된다(프로토콜.md: "호출어 경로에서는 보내지 않는다").
            if self.wake_detected():
                with self._session_condition:
                    self._session_condition.wait_for(
                        lambda: self.be_session_id is not None, timeout=1.0)
        else:
            self.call("session.extend")
        return self.be_session_id

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
        with self._sample_condition:
            dropped = len(self._sample_queue)
            self._sample_closed = True
            self._sample_queue.clear()
            worker = self._sample_worker
            self._sample_condition.notify_all()
        if self.voice_sync is not None:
            self.voice_sync.close()
        try:
            if self.ws:
                self.ws.close()
        except Exception:
            pass
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=1)
        if dropped:
            print(f"[활성 보이스 샘플] 종료로 대기 작업 폐기 count={dropped}")


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
