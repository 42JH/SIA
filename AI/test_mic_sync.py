# -*- coding: utf-8 -*-
"""장치·모델·서버 없이 도는 마이크 동기화 스모크 테스트: python test_mic_sync.py"""
import collections
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from be_link import AgentLink
from brain import Brain, SpeakerAccum
from voice import BLOCK, SR, VoiceListener, _wasapi_dlls, resolve_input_device


def wait_for(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline, "마이크 워커 응답 시간 초과"
        time.sleep(0.005)


class AudioDevice:
    """열기·읽기 실패를 재현하는 가짜 장치 — 실제 PortAudio나 마이크는 쓰지 않는다."""
    def __init__(self):
        self.hosts = [{"name": "Windows WASAPI", "default_input_device": 0}]
        self.devices = [{"name": "Same name", "hostapi": 0, "max_input_channels": 1}
                        for _ in range(3)]
        self.default = SimpleNamespace(device=(0, 0))
        self._initialized = 1
        self.failed = set()
        self.failed_start = set()
        self.attempts = []
        self.streams = []
        self.closed = []
        self.refreshes = 0

    def query_hostapis(self, index=None):
        return self.hosts if index is None else self.hosts[index]

    def query_devices(self, index=None, kind=None):
        return self.devices if index is None else self.devices[index]

    def _terminate(self):
        assert all(not stream.active for stream in self.streams)
        self._initialized -= 1

    def _initialize(self):
        self._initialized += 1
        self.refreshes += 1

    def WasapiSettings(self, **kwargs):
        assert kwargs == {"auto_convert": True}
        return kwargs

    def InputStream(self, **kwargs):
        assert (kwargs["samplerate"], kwargs["channels"], kwargs["dtype"], kwargs["blocksize"]) == (
            SR, 1, "int16", BLOCK)
        index = kwargs["device"]
        wasapi = self.hosts[self.devices[index]["hostapi"]]["name"] == "Windows WASAPI"
        assert kwargs["extra_settings"] == ({"auto_convert": True} if wasapi else None)
        assert all(not stream.active for stream in self.streams), "이전 입력을 먼저 닫아야 함"
        self.attempts.append(index)
        if index in self.failed:
            raise OSError("device unavailable")
        owner = self

        class Stream:
            def __init__(self):
                self.active = False
                self.blocks = collections.deque()
                self.reading = threading.Event()
                self.release = threading.Event()
                self.release.set()
                self.fail_read = False

            def start(self):
                if index in owner.failed_start:
                    raise OSError("stream start failed")
                self.active = True

            def close(self):
                self.active = False
                owner.closed.append(index)

            @property
            def read_available(self):
                if self.fail_read:
                    raise OSError("read failed")
                return BLOCK if self.blocks else 0

            def read(self, count):
                self.reading.set()
                assert self.release.wait(2)
                block = self.blocks.popleft()
                return block if isinstance(block, tuple) else (block, False)

        stream = Stream()
        self.streams.append(stream)
        return stream


def test_dll_handles_reused():
    """동일 DLL을 다시 조회해도 LoadLibrary를 반복하지 않는다."""
    _wasapi_dlls.cache_clear()
    try:
        with patch("voice.ctypes.CDLL") as portaudio, patch("voice.ctypes.WinDLL", create=True) as ole:
            first = _wasapi_dlls("test-portaudio.dll")
            assert _wasapi_dlls("test-portaudio.dll") is first
            portaudio.assert_called_once_with("test-portaudio.dll")
            ole.assert_called_once_with("ole32")
    finally:
        _wasapi_dlls.cache_clear()


def test_endpoint_mapping():
    sd = AudioDevice()
    with patch("voice.wasapi_endpoint_id", side_effect=lambda _, i: f"endpoint-{i}"):
        assert resolve_input_device(sd, "ENDPOINT-2") == 2
        assert resolve_input_device(sd, None) == 0
        for invalid in ("missing", "", 2, {}):
            try:
                resolve_input_device(sd, invalid)
            except (OSError, ValueError):
                pass
            else:
                raise AssertionError("잘못된 엔드포인트를 허용함")
    with patch("voice.wasapi_endpoint_id", return_value="duplicate"):
        try:
            resolve_input_device(sd, "duplicate")
        except OSError:
            pass
        else:
            raise AssertionError("모호한 엔드포인트를 허용함")


def test_settings_and_switch():
    sd, events = AudioDevice(), collections.deque(maxlen=16)
    listener = VoiceListener(events)
    with patch.dict("sys.modules", sounddevice=sd), patch(
            "voice.wasapi_endpoint_id", side_effect=lambda _, i: f"endpoint-{i}"):
        listener.start()
        try:
            wait_for(lambda: len(sd.streams) == 1)
            assert listener.set_settings({"micDeviceId": "endpoint-1"})
            wait_for(lambda: listener.device == 1)
            assert sd.closed == [0]
            assert not listener.set_settings(None)  # hello_ack에는 settings가 없다.
            assert not listener.set_settings({"micDevice": "other"})
            assert not listener.set_settings({"micDeviceId": "endpoint-1"})
            assert listener.device == 1 and sd.attempts == [0, 1]
            old = sd.streams[-1]
            old.blocks.append(np.full((BLOCK, 1), 2000, dtype=np.int16))
            old.release.clear()
            wait_for(old.reading.is_set)
            listener.seg._buf = [np.ones(BLOCK, dtype=np.int16)]
            events.append(("utter", 0, np.ones(BLOCK, dtype=np.int16)))
            assert listener.set_settings({"micDeviceId": "endpoint-2"})
            old.release.set()
            wait_for(lambda: listener.device == 2)
            assert not listener.seg._buf and not listener.seg._preroll
            assert all(event[0] == "reset" for event in events)
            assert listener.set_settings({"micDeviceId": None})
            wait_for(lambda: listener.device == 0)
            assert sd.attempts == [0, 1, 2, 0]
            assert listener.is_alive()
        finally:
            listener.stop()
            listener.join(3)
        assert not listener.is_alive() and sd.closed == [0, 1, 2, 0]


def test_fallback_and_recovery():
    sd, events = AudioDevice(), collections.deque(maxlen=16)
    sd.failed = {1, 0}
    listener = VoiceListener(events)
    listener.set_settings({"micDeviceId": "endpoint-1"})
    with patch.dict("sys.modules", sounddevice=sd), patch(
            "voice.wasapi_endpoint_id", side_effect=lambda _, i: f"endpoint-{i}"):
        listener.start()
        try:
            wait_for(lambda: len(sd.attempts) >= 2)
            assert listener.is_alive() and listener.error is not None
            time.sleep(0.1)
            assert sd.attempts == [1, 0], "실패 후 백오프 없이 재시도함"
            sd.failed.clear()
            wait_for(lambda: listener.device == 1 and listener.error is None)
            notices = [event[1] for event in events if event[0] == "notice"]
            assert len(notices) == 2 and len(set(notices)) == 2
            assert sd.refreshes >= 2
            sd.streams[-1].fail_read = True
            wait_for(lambda: listener.device == 0)
            assert listener.is_alive()
            assert not listener.set_settings({"micDeviceId": "endpoint-1"})
            assert listener.set_settings({"micDeviceId": "endpoint-2"})
            wait_for(lambda: listener.device == 2)
        finally:
            listener.stop()
            listener.join(3)
        assert not listener.is_alive()


def test_reconfigure_during_backoff():
    sd = AudioDevice()
    sd.failed = {0}
    listener = VoiceListener(collections.deque())
    with patch.dict("sys.modules", sounddevice=sd), patch(
            "voice.wasapi_endpoint_id", side_effect=lambda _, i: f"endpoint-{i}"):
        listener.start()
        try:
            wait_for(lambda: listener.error is not None)
            listener.set_settings({"micDeviceId": "endpoint-2"})
            wait_for(lambda: listener.device == 2)
            assert sd.attempts == [0, 2]
        finally:
            listener.stop()
            listener.join(3)


def test_start_failure_closes_before_fallback():
    sd = AudioDevice()
    sd.failed_start = {1}
    listener = VoiceListener(collections.deque())
    listener.set_settings({"micDeviceId": "endpoint-1"})
    with patch.dict("sys.modules", sounddevice=sd), patch(
            "voice.wasapi_endpoint_id", side_effect=lambda _, i: f"endpoint-{i}"):
        listener.start()
        try:
            wait_for(lambda: len(sd.attempts) == 2 and listener.device == 0)
            assert sd.closed == [1] and listener.is_alive()
        finally:
            listener.stop()
            listener.join(3)
        assert sd.closed == [1, 0]


def test_non_wasapi_default_input():
    """다른 호스트의 기본 입력에는 WASAPI 전용 설정을 넘기지 않는다."""
    sd = AudioDevice()
    sd.hosts[0]["name"] = "MME"
    listener = VoiceListener(collections.deque())
    with patch.dict("sys.modules", sounddevice=sd), patch("voice.wasapi_endpoint_id") as lookup:
        listener.start()
        try:
            wait_for(lambda: listener.device == 0)
            assert listener.error is None and sd.attempts == [0]
            lookup.assert_not_called()
        finally:
            listener.stop()
            listener.join(3)
        assert sd.closed == [0]


def test_overflow_preserves_completed_audio():
    """CPU 부하로 끊긴 세그먼트만 버리고 완성된 발화·확인 대기·누적기는 보존한다."""
    brain = Brain.__new__(Brain)
    brain._audio_lock = threading.RLock()
    brain._audio_generation, brain._audio_since = 0, 0
    brain.queue = [("완성된 발화", "화면 캡처")]
    brain._pending = ("창을 닫을까요?",)
    brain._accum = SpeakerAccum()
    accum = brain._accum
    events = collections.deque([("utter", 0, np.ones(BLOCK, dtype=np.int16))])
    sd = AudioDevice()
    listener = VoiceListener(events, on_reset=brain.reset_audio)
    with patch.dict("sys.modules", sounddevice=sd), patch("voice.print") as log:
        listener.start()
        try:
            wait_for(lambda: listener.device == 0)
            stream = sd.streams[-1]
            for _ in range(2):
                with listener._lock:
                    segment = listener.seg
                    segment.recording = True
                    segment._buf = [np.ones(BLOCK, dtype=np.int16)]
                    stream.blocks.append((np.zeros((BLOCK, 1), dtype=np.int16), True))
                wait_for(lambda: listener.seg is not segment)
            assert not listener.seg.recording and not listener.seg._buf
            assert listener._generation == brain._audio_generation == 0
            assert brain.queue == [("완성된 발화", "화면 캡처")]
            assert brain._pending == ("창을 닫을까요?",) and brain._accum is accum
            assert len(events) == 1 and events[0][0] == "utter"
            # 연속 오버플로에서 로그가 쏟아지지 않는다 (장치 이름 같은 다른 줄은 센 적 없다).
            assert sum("오버플로" in str(c) for c in log.call_args_list) == 1
        finally:
            listener.stop()
            listener.join(3)


def test_notice_after_recovery():
    """실패 중 반복 안내는 막되 정상 입력 후 같은 설정에서 재실패하면 다시 알린다."""
    sd, events = AudioDevice(), collections.deque()
    sd.failed = {0}
    listener = VoiceListener(events)
    with patch.dict("sys.modules", sounddevice=sd), patch("voice.MIC_RETRY_S", 0.05):
        listener.start()
        try:
            wait_for(lambda: len(sd.attempts) >= 2)
            assert len([e for e in events if e[0] == "notice"]) == 1
            sd.failed.clear()
            wait_for(lambda: listener.device == 0 and sd.streams[-1].active)
            # 열리기만 한 상태에서는 복구로 보지 않는다.
            assert "unavailable" in listener._reported
            sd.streams[-1].blocks.append(np.zeros((BLOCK, 1), dtype=np.int16))
            wait_for(lambda: not listener._reported)
            sd.failed.add(0)
            sd.streams[-1].fail_read = True
            wait_for(lambda: len([e for e in events if e[0] == "notice"]) == 2)
            attempts = len(sd.attempts)
            wait_for(lambda: len(sd.attempts) > attempts)
            assert len([e for e in events if e[0] == "notice"]) == 2
        finally:
            listener.stop()
            listener.join(3)


def test_pending_audio_reset():
    brain = Brain.__new__(Brain)
    brain._audio_lock = threading.RLock()
    brain._audio_generation = 0
    brain._audio_since = 0
    brain._client = object()
    brain.queue = [("old audio", "old screen")]
    brain._pending = ("old confirmation",)
    brain._accum = SpeakerAccum()
    old_accum = brain._accum
    before = time.monotonic()
    brain.reset_audio()
    assert not brain.queue and brain._pending is None
    assert brain._accum is not old_accum and brain._audio_generation == 1
    brain.submit(None, None, None, t_utter=before)
    assert not brain.queue
    brain.submit(None, None, None)
    assert len(brain.queue) == 1


def test_settings_events_and_notice_contract():
    with patch("be_link.read_runtime", return_value=None):
        link = AgentLink()
    listener = VoiceListener(collections.deque())
    payloads = [
        ("recognition_start", {"settings": {"micDeviceId": "endpoint-1"}}),
        ("hello_ack", {"settingsVersion": 1, "blobs": {}}),
        ("settings_changed", {"settings": {"micDeviceId": "endpoint-1"}}),
        ("settings_changed", {"settings": {"micDeviceId": None}}),
    ]
    for event_type, data in payloads:
        link._on_event(json.dumps({"type": event_type, "data": data}))
    changes = [listener.set_settings(data.get("settings")) for _, data in link.take_events()]
    assert changes == [True, False, False, True] and link.gesture_ready
    sent = []
    link._send = sent.append
    link.notice("microphone unavailable")
    assert sent == [{"type": "notice", "data": {"message": "microphone unavailable"}}]


def test_inflight_audio_is_not_executed_after_switch():
    class Done(BaseException):
        pass

    for switch in (False, True):
        brain = Brain.__new__(Brain)
        brain._audio_lock = threading.RLock()
        brain._audio_generation, brain._audio_since = 0, 0
        brain._client = object()
        brain.queue, brain.busy = [], 0
        brain._pending = brain.speaker = brain.wake = brain.link = None
        brain.wake_template = None
        # 이 검사의 주제는 입력 전환이다 — 세션은 BE 소유가 됐으므로(-320) BE 대역 없이는
        # 세션이 없다. 호출어 판정에 걸리지 않게 게이트만 통과시킨다.
        brain._accum = SpeakerAccum()
        brain.overlay = SimpleNamespace(toast=lambda *a, **k: None, panel=lambda *a, **k: None)
        brain._wake_ok = lambda audio, i_max, lead, oww_pass: (True, "ok", 0.9, 0.0, 1.4)
        brain._try_router = lambda *_: None
        executed = []
        brain._execute = lambda *args: executed.append(args)

        def infer(*_):
            if switch:
                brain.reset_audio()
            return {"action": "test"}

        brain._ask = infer
        brain.submit(np.zeros(SR, dtype=np.int16), None, None)
        with patch("brain.time.sleep", side_effect=Done), patch("brain.log_utterance"), patch(
                "brain.EVAL_CAPTURE", False):
            try:
                brain.run()
            except Done:
                pass
        assert brain._drain(5), "발화 처리 스레드가 끝나지 않았다"   # run() 은 띄우기만 한다(-320)
        assert len(executed) == int(not switch) and brain.busy == 0


def test_slow_execution_does_not_block_audio():
    """액션이 끝나기 전에도 submit·마이크 전환·이벤트 소비가 완료돼야 한다."""
    class Done(BaseException):
        pass

    brain = Brain.__new__(Brain)
    brain._audio_lock = threading.RLock()
    brain._audio_generation, brain._audio_since = 0, 0
    brain._client = object()
    brain.queue, brain.busy = [], 0
    brain._pending = brain.speaker = brain.wake = brain.link = None
    brain.wake_template = None
    brain._accum = SpeakerAccum()
    brain.overlay = SimpleNamespace(toast=lambda *a, **k: None, panel=lambda *a, **k: None)
    # 세션은 BE 소유가 됐다(-320). BE 대역이 없으면 세션도 없어 모든 발화가 호출어 게이트를
    # 탄다 — 이 테스트의 관심사는 '입력이 바뀌면 진행 중 발화를 실행하지 않는다' 라 게이트는 통과시킨다.
    brain._wake_ok = lambda audio, i_max, lead, oww_pass: (True, "ok", 0.9, 0.0, 1.4)
    brain._try_router = lambda *_: {"action": "test"}
    listener = VoiceListener(collections.deque(), on_reset=brain.reset_audio)
    started, release, completed = threading.Event(), threading.Event(), threading.Event()
    errors = []

    def execute(*_):
        started.set()
        release.wait(3)  # 느린 MCP·파일 작업을 재현한다.
        brain._pending = ("이전 액션의 확인 질문",)  # 입력 전환 뒤 늦게 도착한 결과도 재사용하면 안 된다.

    def run():
        # -320 이후 run() 은 발화를 스레드에 넘기고 곧장 돌아온다. 큐가 비면 sleep 에서 Done.
        with patch("brain.time.sleep", side_effect=Done):
            try:
                brain.run()
            except Done:
                pass

    def receive():
        try:
            brain.submit(np.zeros(SR, dtype=np.int16), None, None)
            assert len(brain.queue) == 1
            assert listener.set_settings({"micDeviceId": "endpoint-1"})
            assert listener.take_event()[0] == "reset"
            assert not brain.queue
        except Exception as exc:
            errors.append(exc)
        finally:
            completed.set()

    brain._execute = execute
    brain.submit(np.zeros(SR, dtype=np.int16), None, None)
    worker = threading.Thread(target=run, daemon=True)
    receiver = threading.Thread(target=receive, daemon=True)
    with patch("brain.log_utterance"), patch("brain.EVAL_CAPTURE", False):
        worker.start()
        try:
            assert started.wait(2)
            receiver.start()
            assert completed.wait(1), "느린 액션이 마이크·카메라 루프를 막음"
            assert not errors, errors
        finally:
            release.set()
            worker.join(3)
            if receiver.ident is not None:
                receiver.join(3)
        assert not worker.is_alive() and not receiver.is_alive()
        assert brain._drain(5), "발화 처리 스레드가 끝나지 않았다"
        assert brain._pending is None


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # cp949 콘솔에서도 한글 로그를 남긴다.
    except Exception:
        pass
    tests = [value for name, value in list(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"OK - {len(tests)}/{len(tests)} 마이크 검사 통과")
