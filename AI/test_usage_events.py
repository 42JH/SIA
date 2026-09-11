# -*- coding: utf-8 -*-
"""장치·모델·서버 없이 통계 큐와 실제 발화 실행 경로를 검사한다.

실행: .venv/Scripts/python.exe -u AI/test_usage_events.py
"""
import io
import json
import threading
import time
import urllib.error
import uuid
import wave
from contextlib import contextmanager, redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np

from be_link import AgentLink
from brain import Brain, SpeakerAccum, WAKE_MODEL, wav_bytes
from router import Router
from speaker import SpeakerVerifier
from voice_bridge import VoiceProfileSync


PROFILE = (np.ones(192, dtype=np.float32) / np.sqrt(192), 0.45, 7, "old")
AUDIO = np.full(19200, 1000, dtype=np.int16)  # 말소리 1.2초


def new_link():
    with patch("be_link.read_runtime", return_value=None):
        return AgentLink()


def command(action="open_app", **fields):
    return {"audio_is_speech": True, "is_command": True, "wake_heard": True,
            "action": action, "app": "calc", "say": "완료", "transcript": "REST에 보내지 않는 원문",
            **fields}


@contextmanager
def assistant(profile=PROFILE, act=True):
    with patch("brain.load_api_keys", return_value=[]), patch("brain.EVAL_CAPTURE", False), patch(
            "brain.log_utterance"), patch("brain.be_dom_text", return_value=None):
        link = new_link()
        link.connected, link.be_session_id, link.session_until_mono = True, 128, 100.0
        link._send = Mock(return_value=True)
        link.call = Mock(return_value=(True, {}))
        speaker = None if profile is None else SimpleNamespace(
            snapshot=Mock(return_value=profile), verify=Mock(return_value=(True, 0.87654)))
        brain = Brain(Mock(), act=act, speaker=speaker, link=link)
        brain._client = object()
        brain.router = Router("시아야")
        brain.router.transcribe = Mock(return_value=("시아야 계산기 열어줘", 0.5))
        brain._ask = Mock(return_value=command("answer"))
        clock = SimpleNamespace(now=12.0)
        with patch("brain.time.monotonic", side_effect=lambda: clock.now):
            try:
                yield brain, link, clock
            finally:
                link.close()


def utter(brain, result=None, audio=AUDIO, started=10.0, hwnd=0):
    """무한 워커를 큐가 비는 순간 중단한다. 게이트·실행·통계는 실제 메서드를 쓴다."""
    class Done(BaseException):
        pass

    if result is not None:
        brain.router.transcribe.return_value = ("시아야 이거 해줘", 0.5)  # 실제 라우터에서 LLM 승격
        brain._ask.return_value = result
    brain.submit(audio, None, None, t_utter=started, target_hwnd=hwnd)
    with patch("brain.time.sleep", side_effect=Done):
        try:
            brain.run()
        except Done:
            pass
    assert brain.busy == 0
    assert not any(str(call.args[0]).startswith("오류:") for call in brain.overlay.toast.call_args_list)


def events(link, kind=None):
    return [{k: v for k, v in event.items() if k != "eventUid"}
            for event in link._usage if kind is None or event["kind"] == kind]


def test_queue_uuid_none_and_worker_initialization():
    def worker(target, **_):
        link = target.__self__
        return SimpleNamespace(start=lambda: link.queue_usage("from-worker"))

    with patch("be_link.read_runtime", return_value={"port": 1}), patch(
            "be_link.threading.Thread", side_effect=worker):
        link = AgentLink()
    link.queue_usage("voice", eventUid="untrusted", sessionId=None, accuracy=0.0, payload={"keep": False})
    assert events(link)[1] == {"kind": "voice", "accuracy": 0.0, "payload": {"keep": False}}
    ids = [event["eventUid"] for event in link._usage]
    assert len(set(ids)) == 2 and all(str(uuid.UUID(uid)) == uid and uuid.UUID(uid).version == 4 for uid in ids)


def test_opening_session_waits_for_be_session_id():
    link = new_link()
    sent = threading.Event()
    link._send = lambda _: sent.set() or True

    def reply():
        assert sent.wait(1)
        link._on_event(json.dumps({"type": "session_state", "data": {
            "state": "ACTIVE", "sessionId": 321,
            "deadlineMs": int((time.time() + 30) * 1000)}}))

    worker = threading.Thread(target=reply)
    worker.start()
    assert link.renew(opening=True) == 321
    worker.join(1)
    assert not worker.is_alive()


def test_concurrent_enqueue_during_flush():
    link = new_link()
    link.queue_usage("first")
    started, release = threading.Event(), threading.Event()
    batches = []

    def post(batch):
        batches.append(list(batch))
        started.set()
        assert release.wait(3)
        return {"accepted": len(batch), "duplicates": 0, "rejected": 0}

    link.post_usage_events = post
    flush = threading.Thread(target=link.flush_usage, daemon=True)
    producers = [threading.Thread(target=lambda n=n: [link.queue_usage("voice", index=n * 50 + i)
                                                     for i in range(50)], daemon=True) for n in range(4)]
    flush.start()
    try:
        assert started.wait(2)
        for producer in producers:
            producer.start()
        for producer in producers:
            producer.join(2)
            assert not producer.is_alive(), "전송 중 큐 잠금이 유지됨"
        assert len(link._usage) == 200 and len(batches[0]) == 1
    finally:
        release.set()
        flush.join(3)
    assert not flush.is_alive()
    link.flush_usage()
    link.flush_usage()
    sent = [event for batch in batches for event in batch]
    assert [len(batch) for batch in batches] == [1, 200]
    assert len({event["eventUid"] for event in sent}) == 201
    assert {event["index"] for event in sent[1:]} == set(range(200))


def test_failed_batch_is_discarded_without_retry():
    link = new_link()
    link.queue_usage("discard")

    def fail(_):
        link.queue_usage("keep")  # HTTP 요청 중 들어온 다음 배치
        raise OSError("offline")

    link.post_usage_events = Mock(side_effect=fail)
    output = io.StringIO()
    with redirect_stdout(output):
        link.flush_usage()
    assert "count=1" in output.getvalue() and "offline" in output.getvalue()
    assert events(link) == [{"kind": "keep"}]
    link.post_usage_events.side_effect = None
    link.post_usage_events.return_value = {"accepted": 0, "duplicates": 0, "rejected": 1}
    with redirect_stdout(output):
        link.flush_usage()
        link.flush_usage()
    assert link.post_usage_events.call_count == 2 and not link._usage
    assert [call.args[0][0]["kind"] for call in link.post_usage_events.call_args_list] == ["discard", "keep"]
    assert "accepted=0 duplicates=0 rejected=1" in output.getvalue()


def test_success_pair_session_latency_and_rest_contract():
    with assistant() as (brain, link, clock):
        def call(tool, args=None):
            if tool == "app.launch":
                clock.now = 12.75  # BE 응답까지 포함, 발화 시작(10초) 기준
                link.be_session_id = 999  # 실행 중 세션이 바뀌어도 이미 선택한 세션을 유지한다.
            return True, {}

        link.call.side_effect = call
        utter(brain)
        assert events(link) == [
            {"kind": "voice", "sessionId": 128, "profileId": 7, "accuracy": 0.877, "action": "open_app"},
            {"kind": "command", "sessionId": 128, "action": "open_app", "complexity": "SIMPLE", "latencyMs": 2750}]
        assert [c.args[0] for c in link.call.call_args_list] == ["session.extend", "app.launch"]
        brain._ask.assert_not_called()
        link.rt = {"port": 1234, "token": "test-token"}
        response = Mock()
        response.read.return_value = b'{"accepted":2,"duplicates":0,"rejected":0}'
        clock.now = 99  # 업로드 대기는 이미 확정한 latencyMs에 포함하지 않는다.
        output = io.StringIO()
        with patch("be_link.urllib.request.urlopen") as open_url, redirect_stdout(output):
            open_url.return_value.__enter__.return_value = response
            link.flush_usage()
        request = open_url.call_args.args[0]
        assert request.full_url == "http://127.0.0.1:1234/api/agent/events" and request.method == "POST"
        batch = json.loads(request.data)["events"]
        assert len(batch) == 2 and batch[1]["latencyMs"] == 2750
        assert all("transcript" not in event and "payload" not in event for event in batch)
        assert "count=2 accepted=2 duplicates=0 rejected=0" in output.getvalue()


def test_llm_complex_and_zero_utterance_start():
    with assistant() as (brain, link, clock):
        clock.now = 2.5
        utter(brain, command("answer"), started=0.0)
        brain._ask.assert_called_once()
        assert events(link, "command") == [{"kind": "command", "action": "answer", "sessionId": 128,
                                            "complexity": "COMPLEX", "latencyMs": 2500}]


def test_unregistered_and_disabled_accuracy_omitted():
    for profile in (None, (None, 0.45, None, None)):
        with assistant(profile) as (brain, link, _):
            utter(brain)
            assert events(link, "voice") == [{"kind": "voice", "sessionId": 128, "action": "open_app"}]
            assert len(events(link, "command")) == 1
            if brain.speaker:
                brain.speaker.verify.assert_not_called()


def test_profile_snapshot_and_accumulated_similarity():
    with assistant() as (brain, link, _):
        brain._accum.offer(AUDIO, 0.3, 9.0)
        replies = iter([(False, 0.3), (True, 0.76543)])

        def verify(audio, profile):
            assert profile is PROFILE
            brain.speaker.snapshot.return_value = (PROFILE[0], 0.45, 88, "new")
            return next(replies)

        brain.speaker.verify.side_effect = verify
        utter(brain)
        assert brain.speaker.verify.call_count == 2
        assert len(brain.speaker.verify.call_args.args[0]) == len(AUDIO) * 2
        assert events(link, "voice")[0]["profileId"] == 7
        assert events(link, "voice")[0]["accuracy"] == 0.765
        assert not events(link, "voice-rejected")


def test_measurement_failure_never_becomes_accuracy():
    verifier = SpeakerVerifier.__new__(SpeakerVerifier)
    verifier._profile = PROFILE
    verifier.embed = Mock(side_effect=RuntimeError("embedding unavailable"))
    assert verifier.verify(AUDIO) == (True, None)
    verifier._profile = (None, 0.45, None, None)
    assert verifier.verify(AUDIO) == (True, None)
    for replies in ([(True, None)], [(False, 0.3), (True, None)]):
        with assistant() as (brain, link, _):
            brain.speaker.verify.side_effect = replies
            utter(brain)
            assert "accuracy" not in events(link, "voice")[0]
            assert len(events(link, "command")) == 1


def test_only_long_fresh_final_rejection_emits_ws_and_rest():
    for short, stale, connected in ((False, False, True), (True, False, True),
                                    (False, True, True), (False, False, False)):
        with assistant() as (brain, link, _):
            link.connected = connected
            brain.wake = SimpleNamespace(predict_clip=lambda _: [{WAKE_MODEL.stem: 0.99}])

            def reject(*_):
                if stale:
                    brain.reset_audio()
                return False, 0.3

            brain.speaker.verify.side_effect = reject
            with patch("brain.WAKE_SHADOW", False), patch("brain.SPEAKER_JUDGE_SPEECH_S", 1.2):
                utter(brain, audio=AUDIO[:9600] if short else AUDIO)
            expected = int(not short and not stale and connected)
            assert brain.speaker.verify.call_count == 2  # 누적 음성 재판정까지 실패
            assert sum(c.args[0]["type"] == "voice_rejected" for c in link._send.call_args_list) == expected
            assert events(link) == ([{"kind": "voice-rejected", "sessionId": 128}] if expected else [])
            brain.router.transcribe.assert_not_called()


def test_wake_miss_and_noncommands_emit_nothing():
    with assistant() as (brain, link, _):
        link.session_until_mono = 0
        brain.wake = SimpleNamespace(predict_clip=lambda _: [{WAKE_MODEL.stem: 0.0}])
        with patch("brain.WAKE_SHADOW", False):
            utter(brain)
        assert not events(link)
        brain.speaker.verify.assert_not_called()
    for fields in ({"audio_is_speech": False}, {"is_command": False}, {"wake_heard": False}):
        with assistant() as (brain, link, _):
            link.session_until_mono = 0
            utter(brain, command(**fields))
            assert not events(link)
            assert not any(c.args[0] == "app.launch" for c in link.call.call_args_list)


def test_stale_inference_or_session_renewal_emits_nothing():
    for stage in ("inference", "renewal"):
        with assistant() as (brain, link, _):
            if stage == "inference":
                def infer(*_):
                    brain.reset_audio()
                    return command()
                brain._ask.side_effect = infer
                utter(brain, command())
            else:
                def renew(tool, args=None):
                    assert tool == "session.extend"
                    brain.reset_audio()
                    return True, {}
                link.call.side_effect = renew
                utter(brain)
            assert not events(link)


def test_confirmation_records_original_task_only_after_approval():
    for action, fields in (("window", {"window_op": "close"}), ("delete_file", {"query": "test.txt"})):
        with assistant() as (brain, link, clock), patch("brain.window_title_of", return_value="창"), patch(
                "brain.close_window") as close, patch("brain.resolve_files_by_name", return_value=["test.txt"]):
            utter(brain, command(action, **fields), hwnd=42)
            assert brain._pending and len(events(link, "voice")) == 1 and not events(link, "command")
            close.assert_not_called()
            assert not any(c.args[0] == "files.delete" for c in link.call.call_args_list)
            clock.now, link.be_session_id = 18.0, 256
            utter(brain, command("confirm_yes"), started=16.0, hwnd=99)
            assert brain._pending is None and len(events(link, "voice")) == 2
            assert events(link, "voice")[-1]["sessionId"] == 256
            assert events(link, "command") == [{"kind": "command", "action": action, "sessionId": 128,
                                                "complexity": "COMPLEX", "latencyMs": 4000}]
            if action == "window":
                close.assert_called_once_with(42)
            else:
                link.call.assert_called_with("files.delete", {"paths": ["test.txt"]})


def test_confirmation_cancel_expiry_and_no_pending():
    for reply in ("confirm_no", "expired", "no_pending"):
        with assistant() as (brain, link, clock), patch("brain.window_title_of", return_value="창"), patch(
                "brain.close_window") as close:
            if reply != "no_pending":
                utter(brain, command("window", window_op="close"), hwnd=42)
            clock.now = 30.0 if reply == "expired" else 18.0
            utter(brain, command("confirm_no" if reply == "confirm_no" else "confirm_yes"), started=clock.now)
            close.assert_not_called()
            assert all(e["action"] == "confirm_no" for e in events(link, "command"))
            assert len(events(link, "command")) == int(reply == "confirm_no")


def test_no_actions_never_records_completion():
    for result in (command(), command("media", media_key="mute"), command("answer"), command("end_session")):
        with assistant(act=False) as (brain, link, _):
            utter(brain, result)
            assert not events(link)
            assert all(c.args[0] == "session.extend" for c in link.call.call_args_list)


def test_media_and_session_end_router_paths():
    for text, action, tool in (("시아야 음소거 해줘", "media", "media.mute_toggle"),
                               ("이제 그만", "end_session", None)):
        with assistant() as (brain, link, _):
            brain.router.transcribe.return_value = (text, 0.5)
            utter(brain)
            assert len(events(link, "voice")) == 1
            assert events(link, "command")[0]["action"] == action
            assert events(link, "command")[0]["complexity"] == "SIMPLE"
            assert events(link, "command")[0]["sessionId"] == 128
            if tool:
                assert [c.args[0] for c in link.call.call_args_list] == ["session.extend", tool]
            else:
                link.call.assert_not_called()
                assert any(c.args[0]["type"] == "session_end" for c in link._send.call_args_list)


def test_unexecuted_actions_and_local_mode():
    for result in (command(app="unsupported"), command("web_search", query=""),
                   command("find_file", query=""), command("window", window_op="minimize"),
                   command("media", media_key="forward"), command("none"), command("answer", say="")):
        with assistant() as (brain, link, _):
            utter(brain, result)
            assert len(events(link, "voice")) == 1 and not events(link, "command")
    with assistant() as (brain, link, _), patch("brain.webbrowser.open", return_value=False):
        link.call.return_value = (False, {"code": "FAILED", "message": "검색 실패"})
        utter(brain, command("web_search", query="실패"))
        assert brain.overlay.toast.call_args.args[0] == "검색을 열지 못했습니다"
        assert not events(link, "command")
    with assistant() as (brain, link, _):
        brain.link = None
        utter(brain, command("answer"))
        assert not events(link)
        assert brain.overlay.toast.call_args.args[0] == "완료"


def test_active_sample_put_contract_and_empty_204():
    link = new_link()
    link.rt = {"port": 1234, "token": "secret"}
    expected = wav_bytes(AUDIO)
    response = Mock(status=204)
    with patch("be_link.urllib.request.urlopen") as open_url:
        open_url.return_value.__enter__.return_value = response
        assert link.put_active_voice_sample(expected) == 204
    request = open_url.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:1234/api/agent/voices/active/sample"
    assert request.method == "PUT" and request.get_header("Content-type") == "audio/wav"
    assert request.data == expected and request.data[:4] == b"RIFF" and request.data[8:12] == b"WAVE"
    with wave.open(io.BytesIO(request.data), "rb") as recorded:
        assert recorded.getnchannels() == 1 and recorded.getsampwidth() == 2
        assert recorded.getframerate() == 16000
        assert np.array_equal(np.frombuffer(recorded.readframes(recorded.getnframes()), dtype="<i2"), AUDIO)
    response.read.assert_not_called()
    link.close()


def test_active_sample_success_and_accumulation_use_current_original():
    for accumulated in (False, True):
        with assistant() as (brain, link, _):
            link.rt = {"port": 1, "token": "secret"}
            uploaded, done = [], threading.Event()

            def put(body):
                uploaded.append(body)
                done.set()
                return 204

            link.put_active_voice_sample = Mock(side_effect=put)
            if accumulated:
                brain._accum.offer(AUDIO, 0.3, 9.0)
                brain.speaker.verify.side_effect = [(False, 0.3), (True, 0.76543)]
            utter(brain, command(is_command=False))
            assert done.wait(2) and link.put_active_voice_sample.call_count == 1
            assert uploaded == [wav_bytes(AUDIO)]
            if accumulated:
                assert len(brain.speaker.verify.call_args.args[0]) == len(AUDIO) * 2
            assert not any(call.args[0] == "app.launch" for call in link.call.call_args_list)


def test_active_sample_skips_reject_unregistered_failed_stale_and_no_be():
    for profile in (None, (None, 0.45, None, None)):
        with assistant(profile) as (brain, link, _):
            link.rt = {"port": 1, "token": "secret"}
            link.put_active_voice_sample = Mock(return_value=204)
            utter(brain, command(is_command=False))
            link.put_active_voice_sample.assert_not_called()

    for outcome in ("reject", "measurement", "stale", "no_be"):
        with assistant() as (brain, link, _):
            link.rt = {"port": 1, "token": "secret"}
            link.put_active_voice_sample = Mock(return_value=204)
            if outcome == "reject":
                brain.speaker.verify.return_value = (False, 0.1)
            elif outcome == "measurement":
                brain.speaker.verify.return_value = (True, None)
            elif outcome == "stale":
                def verify(*_):
                    brain.reset_audio()
                    return True, 0.8
                brain.speaker.verify.side_effect = verify
            else:
                link.connected = False
            utter(brain, command(is_command=False))
            link.put_active_voice_sample.assert_not_called()


def test_active_sample_slow_upload_does_not_block_and_keeps_latest_pending():
    with assistant() as (brain, link, _):
        link.rt = {"port": 1, "token": "secret"}
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        second = np.full(len(AUDIO), 2000, dtype=np.int16)
        latest = np.full(len(AUDIO), 3000, dtype=np.int16)
        uploaded = []

        def put(body):
            uploaded.append(body)
            if len(uploaded) == 1:
                started.set()
                assert release.wait(3)
            else:
                finished.set()
            return 204

        link.put_active_voice_sample = Mock(side_effect=put)
        try:
            utter(brain, audio=AUDIO)
            assert started.wait(2) and len(events(link, "command")) == 1
            utter(brain, audio=second, started=11.0)
            utter(brain, audio=latest, started=11.5)
            assert len(events(link, "command")) == 3 and uploaded == [wav_bytes(AUDIO)]
            with link._sample_condition:
                assert len(link._sample_queue) == 1
                assert link._sample_queue[0][0] == wav_bytes(latest)
        finally:
            release.set()
        assert finished.wait(2)
        assert uploaded == [wav_bytes(AUDIO), wav_bytes(latest)]


def test_active_sample_worker_start_failure_preserves_commands_recovery_and_close():
    for recover in (False, True):
        with assistant() as (brain, link, _):
            link.rt = {"port": 1, "token": "secret"}
            done, output = threading.Event(), io.StringIO()
            link.put_active_voice_sample = Mock(side_effect=lambda _: done.set() or 204)
            with patch("be_link.threading.Thread.start", side_effect=RuntimeError("can't start new thread")), \
                    redirect_stdout(output):
                utter(brain)
            assert len(events(link, "command")) == 1
            assert link._sample_worker is None and not link._sample_queue
            link.put_active_voice_sample.assert_not_called()
            assert "워커 시작 실패 error=RuntimeError: can't start new thread" in output.getvalue()
            if recover:
                second = np.full(len(AUDIO), 2000, dtype=np.int16)
                utter(brain, audio=second, started=11.0)
                assert done.wait(2) and len(events(link, "command")) == 2
                link.put_active_voice_sample.assert_called_once_with(wav_bytes(second))
        # 시작 실패 직후와 다음 발화로 복구한 뒤 모두 정상 종료되어야 한다.


def test_active_sample_failures_are_logged_once_without_retry():
    link = new_link()
    errors = [urllib.error.HTTPError("url", 404, "missing", {}, None),
              urllib.error.HTTPError("url", 500, "failed", {}, None),
              urllib.error.URLError("offline")]
    calls, done = [], threading.Event()

    def put(body):
        calls.append(body)
        done.set()
        raise errors[len(calls) - 1]

    link.put_active_voice_sample = put
    output = io.StringIO()
    with redirect_stdout(output):
        for n in range(len(errors)):
            done.clear()
            assert link.queue_active_voice_sample(bytes(n + 1), PROFILE[2:], 0, lambda *_: True)
            assert done.wait(2)  # 각 오류는 실제 전송되도록 대기 샘플 교체를 피한다.
        link.close()
    log = output.getvalue()
    assert len(calls) == 3
    assert "상태 불일치 profileId=7 status=404 bytes=1" in log
    assert "전송 실패 status=500 bytes=2" in log
    assert "전송 실패 error=URLError: <urlopen error offline> bytes=3" in log
    assert "secret" not in log


def test_active_sample_discards_pending_profile_and_input_changes():
    for changed in ("profile", "inactive", "input", "server"):
        link = new_link()
        brain = Brain.__new__(Brain)
        brain._audio_lock = threading.RLock()
        brain._audio_generation, brain._audio_since = 0, 0
        brain.queue, brain._pending, brain._accum = [], None, SpeakerAccum()
        brain.speaker = SimpleNamespace(snapshot=Mock(return_value=PROFILE))
        brain.link = link
        started, release, checked = threading.Event(), threading.Event(), threading.Event()
        sent, checks = [], 0

        def put(body):
            sent.append(body)
            started.set()
            assert release.wait(3)
            return 204

        def current(profile_ref, generation):
            nonlocal checks
            checks += 1
            result = brain._active_voice_sample_is_current(profile_ref, generation)
            if checks == 2:
                checked.set()
            return result

        link.put_active_voice_sample = put
        assert link.queue_active_voice_sample(b"first", PROFILE[2:], 0, current)
        assert started.wait(2)
        assert link.queue_active_voice_sample(b"pending", PROFILE[2:], 0, current)
        if changed == "profile":
            brain.speaker.snapshot.return_value = (PROFILE[0], 0.45, 8, "new")
        elif changed == "inactive":
            brain.speaker.snapshot.return_value = (None, 0.45, None, None)
        elif changed == "input":
            brain.reset_audio()
        else:
            sync = VoiceProfileSync(Mock(), "unused")
            sync.on_changed(None)
            link.voice_sync = sync
        release.set()
        assert checked.wait(2) and sent == [b"first"]
        link.close()


def test_active_sample_close_discards_queue_and_rejects_new_work():
    link = new_link()
    started, release, closed = threading.Event(), threading.Event(), threading.Event()
    sent = []

    def put(body):
        sent.append(body)
        started.set()
        assert release.wait(3)
        return 204

    link.put_active_voice_sample = put
    assert link.queue_active_voice_sample(b"in-flight", PROFILE[2:], 0, lambda *_: True)
    assert started.wait(2)
    assert link.queue_active_voice_sample(b"pending", PROFILE[2:], 0, lambda *_: True)
    closer = threading.Thread(target=lambda: (link.close(), closed.set()))
    closer.start()
    with link._sample_condition:
        assert link._sample_closed and not link._sample_queue
    assert not link.queue_active_voice_sample(b"late", PROFILE[2:], 0, lambda *_: True)
    release.set()
    assert closed.wait(2) and sent == [b"in-flight"]
    closer.join(1)
    assert not closer.is_alive()


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    tests = [value for name, value in list(globals().items()) if name.startswith("test_")]
    for test in tests:
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                test()
        except BaseException:
            print(output.getvalue())
            raise
    print(f"OK - {len(tests)}/{len(tests)} 사용 통계 검사 통과")
