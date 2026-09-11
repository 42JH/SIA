# -*- coding: utf-8 -*-
"""장치·모델·서버 없이 도는 활성 보이스 동기화 검사: python test_voice_sync.py"""
import collections
import hashlib
import io
import json
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np

from be_link import AgentLink
from brain import Brain, SpeakerAccum
from speaker import SpeakerVerifier
from voice import VoiceListener
from voice_bridge import VoiceProfileSync, VoiceSession


def profile_bytes(index=0, **fields):
    centroid = np.zeros(192, dtype=np.float32)
    centroid[index] = 1
    out = io.BytesIO()
    np.savez(out, **({"centroid": centroid, "threshold": 0.25} | fields))
    return out.getvalue()


def reference(body, profile_id=1):
    return {"id": profile_id, "sha256": hashlib.sha256(body).hexdigest()}


def receive(link, event_type, data):
    link._on_event(json.dumps({"type": event_type, "data": data}))


def settled(sync):
    with sync._condition:
        assert sync._condition.wait_for(lambda: not sync._queued and not sync._busy, timeout=3), "동기화 시간 초과"


@contextmanager
def session(body=None):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "speaker.npz"
        speaker = SpeakerVerifier(path)
        sync = VoiceProfileSync(speaker, path)
        with patch("be_link.read_runtime", return_value=None):
            link = AgentLink(voice_sync=sync)
        link.get_voice_npz = Mock(return_value=body if body is not None else profile_bytes())
        try:
            yield link, sync, speaker, path
        finally:
            link.close()
            if sync._worker is not None:
                sync._worker.join(3)
                assert not sync._worker.is_alive(), "종료 후 동기화 워커가 남음"


def test_settings_sync_and_cache():
    """부팅·인식 시작·재접속·활성 변경이 같은 캐시를 사용하고 누락 파일도 복구한다."""
    body = profile_bytes()
    with session(body) as (link, sync, speaker, path):
        reset = Mock()
        receive(link, "hello_ack", {"settingsVersion": 1, "blobs": {"voice": reference(body)}})
        settled(sync)
        assert speaker.profile_id is None and not path.exists()  # 검증만 끝났고 적용은 아직이다.
        assert sync.apply_pending(reset)
        assert speaker.profile_id == 1 and speaker.profile_sha256 == reference(body)["sha256"]
        for event in ("recognition_start", "settings_changed", "hello_ack", "voice_changed"):
            data = reference(body) if event == "voice_changed" else {"blobs": {"voice": reference(body)}}
            receive(link, event, data)
            settled(sync)
            assert not sync.apply_pending(reset)
        assert link.get_voice_npz.call_count == 1 and reset.call_count == 1
        assert link.gesture_ready
        assert [kind for kind, _ in link.take_events()] == [
            "hello_ack", "recognition_start", "settings_changed", "hello_ack"]
        receive(link, "voice_changed", reference(body, 2))
        receive(link, "settings_changed", {"blobs": {"voice": reference(body, 2)}})
        settled(sync)
        assert sync.apply_pending(reset) and speaker.profile_id == 2
        assert link.get_voice_npz.call_count == 1
        path.unlink()
        receive(link, "hello_ack", {"blobs": {"voice": reference(body, 2)}})
        settled(sync)
        sync.apply_pending(reset)
        assert path.read_bytes() == body and link.get_voice_npz.call_count == 2


def test_local_profile_and_missing_key():
    """기존 정상 파일은 다운로드 없이 사용하고 voice 키 누락은 삭제로 해석하지 않는다."""
    body = profile_bytes()
    with session(body) as (link, sync, speaker, path):
        path.write_bytes(body)
        speaker.reload()
        original = speaker.snapshot()
        assert speaker.enrolled and speaker.profile_id is None
        for blobs in ({}, None, {"calib": None}):
            receive(link, "hello_ack", {"blobs": blobs})
        link._on_event('{"type":"voice_changed"}')  # data 누락을 명시적 null로 해석하지 않는다.
        receive(link, "voice_changed", None)  # 삭제는 blobs.voice=null에서만 허용한다.
        assert not sync.apply_pending(Mock()) and speaker.snapshot() is original
        assert path.read_bytes() == body
        receive(link, "hello_ack", {"blobs": {"voice": reference(body)}})
        settled(sync)
        assert sync.apply_pending(Mock()) and speaker.profile_id == 1
        link.get_voice_npz.assert_not_called()
        path.write_bytes(b"broken local cache")
        receive(link, "settings_changed", {"blobs": {"voice": reference(body)}})
        settled(sync)
        sync.apply_pending(Mock())
        assert path.read_bytes() == body and link.get_voice_npz.call_count == 1


def test_null_clears_only_voice_state():
    with session() as (link, sync, speaker, path):
        body = profile_bytes()
        sync.on_changed(reference(body))
        settled(sync)
        sync.apply_pending(Mock())
        other_files = [path.parent / name for name in ("calib.npz", "gestures.npz")]
        for other in other_files:
            other.write_bytes(b"keep")
        brain = Brain.__new__(Brain)
        brain._audio_lock = threading.RLock()
        brain._audio_generation, brain._audio_since = 0, 0
        brain.queue, brain._pending = [("audio", "screen")], ("창을 닫을까요?",)
        brain._accum = SpeakerAccum()
        accum = brain._accum
        events = collections.deque([("utter", 0, np.ones(480, dtype=np.int16))])
        listener = VoiceListener(events, on_reset=brain.reset_audio)
        listener.seg.recording = True
        receive(link, "settings_changed", {"blobs": {"voice": None}})
        with patch("voice_bridge.print") as log:
            assert sync.apply_pending(listener.reset_audio)
            log.assert_called_once_with(
                f"[보이스 동기화] 서버에 사용 중인 목소리가 없어 로컬 프로필을 지운다 — {path}")
        assert not path.exists() and speaker.snapshot() == (None, 0.25, None, None)
        assert not brain.queue and brain._pending is None and brain._accum is not accum
        assert not listener.recording and listener.take_event()[0] == "reset"
        assert all(other.read_bytes() == b"keep" for other in other_files)
        reset = Mock()
        receive(link, "hello_ack", {"blobs": {"voice": None}})
        assert not sync.apply_pending(reset)
        reset.assert_not_called()


def test_failure_preserves_profile_and_retries():
    old_body, new_body = profile_bytes(), profile_bytes(1)
    with session(old_body) as (link, sync, speaker, path):
        sync.on_changed(reference(old_body))
        settled(sync)
        sync.apply_pending(Mock())
        original = speaker.snapshot()
        for result in (OSError("download failed"), b"wrong hash", b"not an npz"):
            link.get_voice_npz.side_effect = result if isinstance(result, Exception) else None
            link.get_voice_npz.return_value = result
            ref = reference(result, 2) if result == b"not an npz" else reference(new_body, 2)
            sync.on_changed(ref)
            settled(sync)
            assert not sync.apply_pending(Mock())
            assert path.read_bytes() == old_body and speaker.snapshot() is original
        link.get_voice_npz.side_effect = None
        link.get_voice_npz.return_value = new_body
        sync.on_changed(reference(new_body, 2))
        settled(sync)
        assert sync.apply_pending(Mock()) and speaker.profile_id == 2


def test_apply_failure_preserves_file_and_id():
    old_body, new_body = profile_bytes(), profile_bytes(1)
    with session(old_body) as (link, sync, speaker, path):
        sync.on_changed(reference(old_body))
        settled(sync)
        sync.apply_pending(Mock())
        original = speaker.snapshot()
        link.get_voice_npz.return_value = new_body
        for fail_callback in (False, True):
            sync.on_changed(reference(new_body, 2))
            settled(sync)
            reset = Mock(side_effect=RuntimeError("reset failed")) if fail_callback else Mock()
            with patch("voice_bridge.os.replace", side_effect=PermissionError("file busy")):
                assert not sync.apply_pending(reset)
            assert path.read_bytes() == old_body and speaker.snapshot() is original
            assert list(path.parent.iterdir()) == [path]


def test_newer_request_wins_during_download():
    old_body, new_body = profile_bytes(), profile_bytes(1)
    with session() as (link, sync, speaker, path):
        started, release = threading.Event(), threading.Event()

        def download():
            if link.get_voice_npz.call_count == 1:
                started.set()
                assert release.wait(3)
                return old_body
            return new_body

        link.get_voice_npz.side_effect = download
        try:
            sync.on_changed(reference(old_body))
            assert started.wait(2)
            receive(link, "settings_changed", {"blobs": {"voice": reference(new_body, 2)}})
            assert not sync.apply_pending(Mock()) and not path.exists()
        finally:
            release.set()
        settled(sync)
        assert sync.apply_pending(Mock()) and path.read_bytes() == new_body
        assert speaker.profile_id == 2 and link.get_voice_npz.call_count == 2


def test_same_hash_new_id_reuses_inflight_download():
    body = profile_bytes()
    with session(body) as (link, sync, speaker, path):
        started, release = threading.Event(), threading.Event()

        def download():
            started.set()
            assert release.wait(3)
            return body

        link.get_voice_npz.side_effect = download
        try:
            receive(link, "voice_changed", reference(body))
            assert started.wait(2)
            receive(link, "settings_changed", {"blobs": {"voice": reference(body)}})
            sync.on_changed(reference(body, 2))
        finally:
            release.set()
        settled(sync)
        assert sync.apply_pending(Mock()) and speaker.profile_id == 2
        assert link.get_voice_npz.call_count == 1


def test_null_and_shutdown_discard_late_download():
    body = profile_bytes()
    for shutdown in (False, True):
        with session(body) as (link, sync, speaker, path):
            path.write_bytes(body)
            speaker.reload()
            old = speaker.snapshot()
            started, release = threading.Event(), threading.Event()

            def download():
                started.set()
                assert release.wait(3)
                return profile_bytes(1)

            link.get_voice_npz.side_effect = download
            try:
                sync.on_changed(reference(profile_bytes(1), 2))
                assert started.wait(2)
                if shutdown:
                    link.close()
                else:
                    receive(link, "hello_ack", {"blobs": {"voice": None}})
                    assert sync.apply_pending(Mock()) and not path.exists()
            finally:
                release.set()
            settled(sync)
            assert not sync.apply_pending(Mock())
            if shutdown:
                assert path.read_bytes() == body and speaker.snapshot() is old
            else:
                assert not path.exists() and not speaker.enrolled and speaker.profile_id is None


def test_profile_validation_and_snapshot():
    malformed = [b"bad zip"] + [profile_bytes(**fields) for fields in (
        {"centroid": np.zeros(192)}, {"centroid": np.ones(2)},
        {"centroid": np.full(192, np.nan)}, {"centroid": np.array([None] * 192, dtype=object)},
        {"threshold": np.nan}, {"threshold": 2}, {"threshold": [0.25]})]
    for body in malformed:
        try:
            SpeakerVerifier.read_profile(io.BytesIO(body))
        except (ValueError, KeyError, OSError):
            pass
        else:
            raise AssertionError("잘못된 보이스 npz를 허용함")
    with session() as (_, _, speaker, _):
        first = SpeakerVerifier.read_profile(io.BytesIO(profile_bytes()))
        second = SpeakerVerifier.read_profile(io.BytesIO(profile_bytes(1)))
        speaker.apply_profile(*first, 1, "old")
        snapshot = speaker.snapshot()

        def embed(_):
            speaker.apply_profile(*second, 2, "new")
            return first[0]

        speaker.embed = embed
        assert speaker.verify(np.zeros(480), snapshot) == (True, 1.0)
        assert speaker.profile_id == 2 and snapshot[2] == 1


def test_disabled_sync_and_registration_delegation():
    with patch("be_link.read_runtime", return_value=None):
        link = AgentLink()  # --no-speaker와 같은 주입 상태. 파일 접근·다운로드가 없다.
    link._agent_request = Mock(side_effect=AssertionError("비활성 상태에서 다운로드함"))
    for kind in ("hello_ack", "recognition_start", "settings_changed"):
        receive(link, kind, {"blobs": {"voice": None}})
    receive(link, "voice_changed", reference(profile_bytes()))
    link._agent_request.assert_not_called()
    link.close()
    with session() as (link, sync, speaker, path):
        assert sync._worker is None  # BE 이벤트 없는 단독 동작에서는 로컬 프로필에 손대지 않는다.
        registration = VoiceSession(link, speaker, path)
        with patch.object(sync, "on_changed") as update:
            registration.on_changed(reference(profile_bytes()))
            update.assert_called_once_with(reference(profile_bytes()))


def test_profile_change_keeps_microphone_stream():
    """마이크 읽기 도중 프로필을 교체해도 입력은 유지하고 이전 화자의 블록만 버린다."""
    from test_mic_sync import AudioDevice, wait_for

    sd = AudioDevice()
    listener = VoiceListener(collections.deque())
    with session() as (_, sync, speaker, _), patch.dict("sys.modules", sounddevice=sd):
        listener.start()
        try:
            wait_for(lambda: listener.device == 0)
            stream = sd.streams[0]
            stream.release.clear()
            stream.blocks.append(np.full((480, 1), 10, dtype=np.int16))
            wait_for(stream.reading.is_set)
            sync.on_changed(reference(profile_bytes()))
            settled(sync)
            assert sync.apply_pending(listener.reset_audio)
            assert listener.take_event()[0] == "reset" and speaker.profile_id == 1
            stream.release.set()
            stream.blocks.append(np.full((480, 1), 20, dtype=np.int16))
            wait_for(lambda: len(listener.seg._preroll) == 1)
            assert np.all(listener.seg._preroll[0] == 20)
            assert sd.attempts == [0] and not sd.closed
        finally:
            if sd.streams:
                sd.streams[0].release.set()
            listener.stop()
            listener.join(3)


def test_download_request_has_no_conditional_header():
    with patch("be_link.read_runtime", return_value=None):
        link = AgentLink()
    link.rt = {"port": 1234, "token": "test-token"}
    response = Mock()
    response.read.return_value = b"npz"
    with patch("be_link.urllib.request.urlopen") as open_url:
        open_url.return_value.__enter__.return_value = response
        assert link.get_voice_npz() == b"npz"
        request = open_url.call_args.args[0]
        assert request.full_url == "http://127.0.0.1:1234/api/agent/voices/active/npz"
        assert request.get_header("Authorization") == "Bearer test-token"
        assert request.get_header("If-none-match") is None
        assert request.get_header("Accept") == "application/octet-stream"
    link.close()


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    tests = [value for name, value in list(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
    print(f"OK - {len(tests)}/{len(tests)} 보이스 동기화 검사 통과")
