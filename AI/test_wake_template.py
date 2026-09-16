# -*- coding: utf-8 -*-
"""장치·모델·서버 없이 도는 호출어 개인화 검사: python test_wake_template.py

개인화 템플릿의 저장 형식, 호출어 구간 분리, 그리고 등록·로컬 파일·BE blob 사이의 동기화 규칙을 본다.
합성 임베딩으로 처리 흐름을 검사한다. 실제 화자 구별 성능과 임계값은 별도 실측으로 확인한다.
등록 진행(wakeword_*)은 test_core의 test_wake_enroll에서 검사한다. 설정 호출어는 "시아야"를 사용한다.
"""
import hashlib
import io
import json
import tempfile
import threading
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from be_link import AgentLink
from brain import (WAKE_CLIP_TAIL_JOIN_S, WAKE_FRAME_S, WAKE_PAD_S, speech_span, wake_clip,
                   wake_clip_is_clean, wake_only)
from speaker import EMBED_DIM, MODEL_SOURCE, WakeTemplate
from voice_bridge import WakeEnroll, WakeTemplateStore


def unit(k):
    """k번 축만 1인 정규화된 임베딩 — 서로 다른 템플릿을 만드는 데 쓴다."""
    emb = np.zeros(EMBED_DIM, np.float32)
    emb[k] = 1.0
    return emb


def template(k=0):
    return WakeTemplate("시아야", (0.99,), np.stack([unit(k)] * 5), 5)


def settle(check):
    """조건이 참이 될 때까지 최대 3초 기다린다 — 워커가 끝났는지 명시적으로 본다."""
    for _ in range(60):
        if check():
            return True
        threading.Event().wait(0.05)
    return False


def test_wake_template_npz():
    """호출어 템플릿 npz 저장·복원과 검증 — 형식 버전·임베딩 모델·차원이 다르면 읽지 않는다.
    서버에서 받은 바이트를 그대로 믿고 판정 기준으로 쓰면 안 되기 때문이다."""
    emb = unit(0)
    t = WakeTemplate("시아야", (0.99,), np.stack([emb] * 5), 5, 3)
    back = WakeTemplate.read(io.BytesIO(t.npz_bytes()))
    assert back.wake_text == "시아야" and back.base_n == 5 and back.profile_id == 3 and back.bound
    assert back.extractor == MODEL_SOURCE and np.allclose(back.embs, t.embs)

    def broken(**fields):
        buf = io.BytesIO()
        base = {"version": 2, "extractor": MODEL_SOURCE, "sr": 16000, "wake_text": "시아야",
                "scores": np.asarray([0.99], np.float32), "embs": np.stack([emb]),
                "base_n": 1, "profile_id": -1}
        np.savez(buf, **(base | fields))
        return buf.getvalue()

    for fields in ({"version": 1}, {"extractor": "other/model"}, {"sr": 8000}, {"base_n": 0},
                   {"base_n": 5}, {"wake_text": "  "}, {"embs": np.stack([emb * 2])},
                   {"embs": np.zeros((1, 8), np.float32)},
                   {"scores": np.asarray([np.nan], np.float32)},
                   {"embs": np.stack([emb] * 12), "base_n": 1}):   # 이전 파일 형식의 추가 행 상한 초과
        try:
            WakeTemplate.read(io.BytesIO(broken(**fields)))
        except (ValueError, KeyError, OSError):
            continue
        raise AssertionError(f"잘못된 템플릿을 허용함: {fields}")


def test_wake_uses_only_enrolled_samples():
    """원본 등록 샘플만 비교한다. 호출어 판정으로 파일 저장이나 업로드가 발생하지 않는지 확인한다."""
    from brain import Brain
    from test_usage_events import assistant

    legacy = WakeTemplate("시아야", (0.99,), np.vstack([np.stack([unit(0)] * 5), unit(1)]), 5, 7)
    loaded = WakeTemplate.read(io.BytesIO(legacy.npz_bytes()))
    assert len(loaded.embs) == 6 and loaded.base_n == 5
    assert loaded.similarity(unit(0)) == 1.0 and loaded.similarity(unit(1)) == 0.0
    audio = np.concatenate([np.zeros(6400, np.int16), np.full(12800, 1000, np.int16), np.zeros(9600, np.int16)])
    peak = int(round((speech_span(audio)[1] + WAKE_PAD_S) / WAKE_FRAME_S))
    with tempfile.TemporaryDirectory() as directory, assistant() as (brain, _, _):
        store = WakeTemplateStore(Path(directory) / "wake.npz")
        try:
            store.commit(loaded, "이전 파일")
            body, generation = store.path.read_bytes(), store.generation
            brain.wake_template, brain.wake = store, object()
            brain.speaker.profile_id = 7
            brain._wake_ok = Brain._wake_ok.__get__(brain)
            with patch.object(store, "commit") as commit, patch.object(store, "_queue_upload") as upload:
                brain.speaker.embed = lambda _: unit(1)
                assert brain._wake_ok(audio, peak, 0, True)[:2] == (False, "speaker")
                brain.speaker.embed = lambda _: unit(0)
                assert brain._wake_ok(audio, peak, 0, True)[:2] == (True, "ok")
                commit.assert_not_called()
                upload.assert_not_called()
            assert store.path.read_bytes() == body and store.generation == generation
        finally:
            store.close()


def test_wake_clip_speaker_separation():
    """호출어 구간에 뒤이은 다른 사람의 표본이 몇 개나 섞이는가 — 표본 하나까지 센다.
    쉬었다 말하면 0, 쉬지 않고 이어지면 꼬리만큼 섞이고 그 구간은 등록 품질 검사에서 걸러진다.
    NOTE(한계): 신호 길이만 보는 휴리스틱이라 화자를 실제로 가르지는 못한다 — 실제 녹음으로는 안 쟀다."""
    own, other = 1000, 2000
    head = np.concatenate([np.zeros(6400, np.int16), np.full(12800, own, np.int16)])
    tail = np.full(int(1.2 * 16000), other, np.int16)
    peak = max(0, int(round((speech_span(head)[1] + WAKE_PAD_S) / WAKE_FRAME_S)))

    def leak(clip):
        return np.count_nonzero(np.asarray(clip) == other) / 16000

    for pause in (0.1, 0.3, 0.6):                      # 짧게라도 쉬면 한 표본도 안 들어온다
        audio = np.concatenate([head, np.zeros(int(pause * 16000), np.int16), tail])
        clip, _, _, certain = wake_clip(audio, peak)
        assert certain and np.any(clip == own) and not leak(clip), pause

    joined = np.concatenate([head, tail])              # 휴지 없이 이어진 발화
    for shift in (-2, -1, 0, 1, 2):                    # 최고점이 실제 끝에서 어긋난 경우까지
        clip, _, end, certain = wake_clip(joined, peak + shift)
        mixed = leak(clip)
        assert mixed <= WAKE_CLIP_TAIL_JOIN_S + (max(shift, 0) + 1) * WAKE_FRAME_S, (shift, mixed)
        if mixed:                                      # 섞인 구간은 등록에 쓰지 않는다
            assert not wake_clip_is_clean(joined, clip, end, certain)[0], shift


def test_wake_only_keeps_attached_commands():
    """단독 호출만 빠르게 끝낸다 — 짧은 명령·연속 발화·불확실한 경계는 기존 경로에 남긴다."""
    head = np.concatenate([np.zeros(6400, np.int16), np.full(12800, 1000, np.int16)])
    silence = np.zeros(9600, np.int16)
    peak = int(round((speech_span(head)[1] + WAKE_PAD_S) / WAKE_FRAME_S))
    assert wake_only(np.concatenate([head, silence]), peak)
    for pause in (0, 0.1, 0.4):
        for duration in (0.12, 0.3, 1.5):
            audio = np.concatenate([head, np.zeros(int(pause * 16000), np.int16),
                                    np.full(int(duration * 16000), 2000, np.int16), silence])
            assert not wake_only(audio, peak), (pause, duration)
    assert not wake_only(np.concatenate([head, silence]), None)
    assert not wake_only(np.concatenate([head, silence]), 0)  # 최고점이 말소리보다 앞에 찍힘
    assert not wake_only(np.zeros(32000, np.int16), peak)
    assert not wake_only(np.full(48000, 1000, np.int16), peak)  # 배경음·잘린 구간
    lead = 16000
    assert wake_only(np.concatenate([np.zeros(lead, np.int16), head, silence]), peak, lead)
    fast = np.concatenate([np.zeros(6720, np.int16), np.full(2400, 1000, np.int16), silence])  # 말소리 0.15초
    fast_peak = int(round((speech_span(fast)[1] + WAKE_PAD_S) / WAKE_FRAME_S))
    assert wake_only(fast, fast_peak)
    clip, _, end, certain = wake_clip(fast, fast_peak)
    assert wake_clip_is_clean(fast, clip, end, certain)[2] == "TOO_SHORT"  # 등록 하한은 유지


def test_wake_only_run_skips_command_processing():
    """실제 개인화 게이트와 워커를 지난 단독 호출은 듣기만 시작한다. 이어진 명령은 화자인증을 거친다."""
    from brain import Brain
    from test_usage_events import assistant, events, utter

    head = np.concatenate([np.zeros(6720, np.int16), np.full(6240, 1000, np.int16)])  # 빠른 호출 회귀
    silence = np.zeros(9600, np.int16)
    peak = int(round((speech_span(head)[1] + WAKE_PAD_S) / WAKE_FRAME_S))
    for active, owner, attached, local in ((False, True, False, False), (True, True, False, False),
                                          (False, False, False, False), (True, False, False, False),
                                          (False, True, True, False), (False, True, False, True)):
        with tempfile.TemporaryDirectory() as directory, assistant() as (brain, link, clock):
            store = WakeTemplateStore(Path(directory) / "wake.npz")
            try:
                store.commit(template().bound_to(7), "등록")
                brain.wake_template, brain.wake = store, object()
                brain._wake_ok = Brain._wake_ok.__get__(brain)
                brain.speaker.profile_id = 7
                brain.speaker.embed = lambda _: unit(0 if owner else 1)
                brain.speaker.verify.return_value = (False, 0.1)  # 이어진 명령에는 화자 인증이 필요하다
                link.connected = not local
                link.session_until_mono = 100.0 if active else 0.0
                audio = np.concatenate([head, np.full(16000, 2000, np.int16), silence]) if attached else np.concatenate([head, silence])
                with patch("brain.wake_score_of", return_value=(0.99, peak, 0)), patch("brain.log_utterance") as log:
                    utter(brain, audio=audio)
                if owner and not attached:
                    assert log.call_args.kwargs["gate"] == "wake_only"
                    brain.speaker.verify.assert_not_called()
                    assert any(c.args[0] == "네, 듣고 있어요" for c in brain.overlay.toast.call_args_list)
                    assert not brain._accum.n_joined
                    if local:
                        assert brain.session_until > clock.now
                elif attached:
                    brain.speaker.verify.assert_called_once()
                    assert log.call_args.kwargs["gate"] == "speaker_reject"
                else:
                    assert log.call_args.kwargs["gate"] == "wake_reject"
                    brain.speaker.verify.assert_not_called()
                brain.router.transcribe.assert_not_called()
                brain._ask.assert_not_called()
                wakes = [c for c in link._send.call_args_list if c.args[0]["type"] == "wakeword_detected"]
                assert len(wakes) == int(owner and not active and not local)
                assert not events(link, "command")
            finally:
                store.close()


def test_wake_only_preserves_confirmation_and_shadow():
    """확인 대기·섀도 모드는 단독 호출 단축 경로를 타지 않는다."""
    from test_usage_events import assistant, utter

    audio = np.concatenate([np.zeros(6400, np.int16), np.full(12800, 1000, np.int16), np.zeros(9600, np.int16)])
    peak = int(round((speech_span(audio)[1] + WAKE_PAD_S) / WAKE_FRAME_S))
    for shadow in (False, True):
        with assistant() as (brain, link, _):
            brain.wake = object()
            brain.router.transcribe.return_value = ("시아야", 0.1)
            if not shadow:
                brain._pending = ("닫을까요?", "test", 100.0)
            with patch("brain.wake_score_of", return_value=(0.99, peak, 0)), patch("brain.WAKE_SHADOW", shadow), patch.object(brain, "_execute", return_value=None):
                utter(brain, audio=audio)
            brain.speaker.verify.assert_called_once()
            brain._ask.assert_called_once()


def test_wake_template_store():
    """호출어 템플릿 저장소 — 검사와 저장 사이에 삭제가 끼어들면 지워진 등록본이 되살아나지 않고,
    서버 쓰기는 순번대로 한 줄로 나가며, 만료된 본문은 큐에 들이지 않고, 우리가 보낸 본문의
    알림을 남의 등록본으로 오인하지 않으며, 확인과 저장 사이에 들어온 최신 요청을 잃지 않는다."""
    sent, gate = [], {}

    def hold():
        """다음 PUT 하나를 붙잡는다 → (시작됨, 풀기)."""
        gate["pending"] = (threading.Event(), threading.Event())
        return gate["pending"]

    def put(url, body, ctype):
        pending = gate.pop("pending", None)
        if pending:
            pending[0].set()
            assert pending[1].wait(3)
        if gate.get("fail"):
            raise OSError("서버 없음")
        sent.append(body)

    with tempfile.TemporaryDirectory() as directory:
        store = WakeTemplateStore(Path(directory) / "wake.npz", link=SimpleNamespace(rt={"port": 1}))
        store.put = put
        store.commit(template(), "준비")

        # 1) 파일을 만든 뒤 교체 직전에 삭제가 들어오면 그 저장은 폐기된다
        generation, real_prepare = store.generation, store._prepare
        store._prepare = lambda t: (real_prepare(t), store.clear("저장 중 삭제"))[0]
        assert store.commit(template(1), "등록", generation=generation) is None
        assert store.current is None and not store.path.exists()
        store._prepare = real_prepare
        assert store.commit(template(), "재등록")            # 방해가 없으면 같은 경로로 저장된다

        # 2) 먼저 시작해 늦게 끝난 쓰기가 새 등록본을 덮지 않는다 (순번대로 한 줄로 나간다)
        first, first_seq = template(2).npz_bytes(), store.reserve_write()[0]
        started, release = hold()
        store._queue_upload(first, first_seq)
        assert started.wait(2)
        newest = template(3).npz_bytes()
        newest_seq, _ = store.reserve_write()
        worker = threading.Thread(target=lambda: store.write_blob(newest, newest_seq))
        worker.start()
        release.set()
        worker.join(5)
        assert settle(lambda: len(sent) == 2) and sent[-1] == newest

        # 3) 쓰는 중에 들어온 자기 PUT 의 알림은 남의 등록본이 아니다 — 내려받지 않는다.
        #    응답 전에 와도, 응답 뒤에 와도 같다
        mine, mine_seq = template(4).npz_bytes(), store.reserve_write()[0]
        started, release = hold()
        worker = threading.Thread(target=lambda: store.write_blob(mine, mine_seq))
        worker.start()
        assert started.wait(2)
        assert not store.on_blob(hashlib.sha256(mine).hexdigest())   # 응답 전 알림
        release.set()
        worker.join(5)
        assert not store.on_blob(hashlib.sha256(mine).hexdigest())   # 응답 뒤 알림
        assert store._worker is None and not store._queued           # 내려받기를 시작하지 않았다

        # 4) 오래된 요청이 큐에서 대기 중인 최신 작업을 밀어내지 못한다
        stale_body, stale_seq = template(5).npz_bytes(), store.reserve_write()[0]
        started, release = hold()
        store._queue_upload(stale_body, stale_seq)          # 워커가 집어 들고 PUT 에 매달린다
        assert started.wait(2)
        latest, latest_seq = template(6).npz_bytes(), store.reserve_write()[0]
        assert store._queue_upload(latest, latest_seq)      # 최신 C 가 큐에서 기다린다
        dropped = store.dropped
        assert not store._queue_upload(stale_body, stale_seq)   # 늦게 들어온 이전 본문 B
        assert store.dropped == dropped + 1 and store._upload[1] == latest
        release.set()
        assert settle(lambda: sent[-1] == latest)           # C 는 실제로 나간다
        store.close()

    # 5) A 를 확정하는 사이 B 참조가 들어오면 A 는 폐기되고 B 는 요청이 살아남아 이어서 적용된다
    bodies = [template(7).npz_bytes(), template(8).npz_bytes()]
    shas = [hashlib.sha256(b).hexdigest() for b in bodies]
    ready, go, fetched = threading.Event(), threading.Event(), []
    with tempfile.TemporaryDirectory() as directory:
        store = WakeTemplateStore(Path(directory) / "wake.npz",
                                  link=SimpleNamespace(rt={"port": 1},
                                                       get_blob_npz=lambda name: bodies[len(fetched)]))
        store.link.get_blob_npz = lambda name: (fetched.append(1), bodies[len(fetched) - 1])[1]
        real_prepare = store._prepare

        def prepare(t):
            prepared = real_prepare(t)
            if len(fetched) == 1:            # A 의 임시 파일을 만든 직후 B 참조가 들어온다
                ready.set()
                assert go.wait(3)
            return prepared

        store._prepare = prepare
        store.on_blob(shas[0])
        assert ready.wait(3)
        store.on_blob(shas[1])               # 확인과 저장 사이에 들어온 최신 요청
        go.set()
        assert settle(lambda: store._local_sha() == shas[1])   # 추가 알림 없이 B 가 적용된다
        assert len(fetched) == 2
        store.close()

    # 6) 쓰는 중에 온 다른 참조는 미뤄 뒀다가 쓰기가 끝나면 내려받아 적용한다.
    #    쓰기가 실패해 재시도까지 다 소진해도 그 처리가 멈추지 않는다
    other = template(9).npz_bytes()
    other_sha = hashlib.sha256(other).hexdigest()
    for failing in (False, True):
        with tempfile.TemporaryDirectory() as directory, patch("voice_bridge.WAKE_UPLOAD_RETRY_S", 0.01):
            store = WakeTemplateStore(Path(directory) / "wake.npz",
                                      link=SimpleNamespace(rt={"port": 1},
                                                           get_blob_npz=lambda name: other))
            store.put = put
            gate["fail"] = failing
            mine, mine_seq = template(10).npz_bytes(), store.reserve_write()[0]
            started, release = hold()
            store._queue_upload(mine, mine_seq)
            assert started.wait(2)
            assert not store.on_blob(other_sha)           # 쓰는 중이라 미뤄 둔다
            assert store._want == other_sha and not store._queued
            release.set()
            assert settle(lambda: store._local_sha() == other_sha), failing
            gate.pop("fail")
            store.close()

    # 6-2) 직접 쓰기(등록·CLI 경로)가 예외로 끝나도 미뤄 둔 참조는 재개된다
    with tempfile.TemporaryDirectory() as directory:
        store = WakeTemplateStore(Path(directory) / "wake.npz",
                                  link=SimpleNamespace(rt={"port": 1},
                                                       get_blob_npz=lambda name: other))
        store.put = put
        gate["fail"] = True
        raised, seq = [], store.reserve_write()[0]

        def direct():
            try:
                store.write_blob(template(13).npz_bytes(), seq)
            except OSError:
                raised.append(1)

        started, release = hold()
        worker = threading.Thread(target=direct)
        worker.start()
        assert started.wait(2)
        assert not store.on_blob(other_sha)            # 쓰는 중이라 미뤄 둔다
        release.set()
        worker.join(5)
        gate.pop("fail")
        assert raised and settle(lambda: store._local_sha() == other_sha)
        store.close()

    # 6-3) 다시 보낼 업로드가 남아 있는 동안에는 보류를 유지한다 (쓰기와 내려받기를 뒤섞지 않는다)
    with tempfile.TemporaryDirectory() as directory:
        store = WakeTemplateStore(Path(directory) / "wake.npz",
                                  link=SimpleNamespace(rt={"port": 1},
                                                       get_blob_npz=lambda name: other))
        store._want, store._upload = other_sha, (store._write_seq, other, 1)
        store._resume_fetch()
        assert not store._queued                       # 재시도가 남아 있으면 내려받지 않는다
        store._upload = None
        store._resume_fetch()
        assert store._queued                           # 남은 쓰기가 없으면 그때 내려받는다
        store.close()

    # 7) A 를 올린 뒤 서버가 B 로 바뀌어 내려받았고, 다시 A 로 돌아왔다는 알림이 오면 A 를 적용한다 —
    #    과거에 보냈다는 이유만으로 정상적인 서버 변경을 무시하지 않는다
    a, b = template(11).npz_bytes(), template(12).npz_bytes()
    sha_a, sha_b = hashlib.sha256(a).hexdigest(), hashlib.sha256(b).hexdigest()
    serving = {"body": b}
    with tempfile.TemporaryDirectory() as directory:
        store = WakeTemplateStore(Path(directory) / "wake.npz",
                                  link=SimpleNamespace(rt={"port": 1},
                                                       get_blob_npz=lambda name: serving["body"]))
        store.put = put
        assert store.write_blob(a, store.reserve_write()[0])
        assert store.on_blob(sha_b)                       # 서버는 B 다 — 내려받아 적용한다
        assert settle(lambda: store._local_sha() == sha_b)
        serving["body"] = a
        assert store.on_blob(sha_a)                       # 서버가 A 로 돌아왔다
        assert settle(lambda: store._local_sha() == sha_a)
        store.close()

    # 8) 보내지 못한 sha 는 가리지 않는다 — 서버 참조로 복구할 길이 막히면 안 된다
    with tempfile.TemporaryDirectory() as directory:
        store = WakeTemplateStore(Path(directory) / "wake.npz",
                                  link=SimpleNamespace(rt={"port": 1}, get_blob_npz=lambda name: a))
        store.put = put
        gate["fail"] = True
        try:
            store.write_blob(a, store.reserve_write()[0])
        except OSError:
            pass
        gate.pop("fail")
        assert store.on_blob(sha_a)                       # 서버에는 A 가 있다고 알려 왔다
        assert settle(lambda: store._local_sha() == sha_a)
        store.close()


def test_wake_enroll_local_failure_recovers_from_server():
    """서버에 저장한 뒤 로컬 준비·교체가 실패해도, 같은 서버 참조로 복구하고 등록을 마칠 수 있다."""
    for failure in ("prepare", "replace"):
        with tempfile.TemporaryDirectory() as directory:
            sent, remote, gets = [], {}, []

            def get(name):
                gets.append(name)
                return remote["body"]

            link = SimpleNamespace(rt={"port": 1}, get_blob_npz=get, _send=sent.append)
            store = WakeTemplateStore(Path(directory) / "wake.npz", link)
            try:
                store.commit(template(), "이전 등록")
                generation, puts = store.generation, []

                def put(url, body, ctype):
                    puts.append(body)
                    remote["body"] = body
                    assert not store.on_blob(hashlib.sha256(body).hexdigest())  # 응답 전 자기 알림
                    assert store.generation == generation

                store.put = put
                enroll = WakeEnroll(link, SimpleNamespace(profile_id=3), store)
                enroll.active, enroll.epoch = True, 1
                enroll._samples = [np.zeros(16000, np.int16)] * 5
                enroll._embs, enroll._scores = [unit(1)] * 5, [0.99] * 5
                fail = (patch.object(store, "_prepare", side_effect=OSError("저장 준비 실패"))
                        if failure == "prepare" else
                        patch("voice_bridge.os.replace", side_effect=OSError("파일 사용 중")))
                with fail:
                    enroll._finish(1)
                assert not any(msg["type"] == "wakeword_done" for msg in sent)
                assert np.array_equal(store.current.embs, template().embs)  # 실패 전 등록본은 유지한다
                sha = hashlib.sha256(remote["body"]).hexdigest()
                assert store.on_blob(sha), failure         # 파일 오류가 해소되면 서버 참조를 다시 받는다
                assert settle(lambda: store._local_sha() == sha)
                assert gets == ["wakeword"]
                enroll._finish(1)                         # 모은 5개로 등록 완료 — 재업로드는 하지 않는다
                assert len(puts) == 1 and len(enroll._samples) == 5
                assert sent[-1]["type"] == "wakeword_done" and not enroll.active
            finally:
                store.close()
                if store._worker is not None:
                    store._worker.join(3)


def test_wake_failed_commit_preserves_newer_write():
    """이전 저장의 실패 정리가, 그 사이 시작한 새 PUT 의 자기 알림 보호까지 지우면 안 된다."""
    with tempfile.TemporaryDirectory() as directory:
        store = WakeTemplateStore(Path(directory) / "wake.npz", SimpleNamespace(rt={"port": 1}))
        store.put = lambda *args: None
        newer = template(1).npz_bytes()

        def prepare(t):
            assert store.write_blob(newer, store.reserve_write()[0])
            raise OSError("이전 저장 실패")

        try:
            with patch.object(store, "_prepare", side_effect=prepare):
                assert store.commit(template(), "이전 등록") is None
            assert not store.on_blob(hashlib.sha256(newer).hexdigest())
            assert store._worker is None
        finally:
            store.close()


def test_wake_settings_before_download():
    """recognition_start 의 설정을 먼저 반영한 세대로 같은 이벤트의 템플릿을 내려받는다."""
    with tempfile.TemporaryDirectory() as directory:
        store = WakeTemplateStore(Path(directory) / "wake.npz")
        with patch("be_link.read_runtime", return_value=None):
            link = AgentLink(wake_store=store)
        body = template().npz_bytes()
        started, release, seen = threading.Event(), threading.Event(), []

        def get(name):
            seen.append(store.setting_word)
            started.set()
            assert release.wait(3)
            return body

        link.get_blob_npz = get
        real_blob = store.on_blob

        def on_blob(sha):
            result = real_blob(sha)
            assert started.wait(3)                         # 다운로드가 세대를 읽은 뒤 이벤트 처리를 이어 간다
            return result

        try:
            sha = hashlib.sha256(body).hexdigest()
            with patch.object(store, "on_blob", side_effect=on_blob):
                link._on_event(json.dumps({"type": "recognition_start", "data": {
                    "settings": {"wakeWord": "시아야"}, "blobs": {"wakeword": sha}}}))
            release.set()
            assert seen == ["시아야"]
            assert settle(lambda: store._local_sha() == sha)
        finally:
            release.set()
            store.close()
            if store._worker is not None:
                store._worker.join(3)


def test_wake_download_retries_after_settings_change():
    """hello_ack 로 받는 도중 별도 설정이 와도, 추가 blob 알림 없이 최신 참조를 다시 적용한다."""
    with tempfile.TemporaryDirectory() as directory:
        store = WakeTemplateStore(Path(directory) / "wake.npz")
        with patch("be_link.read_runtime", return_value=None):
            link = AgentLink(wake_store=store)
        body = template().npz_bytes()
        started, release, gets = threading.Event(), threading.Event(), []

        def get(name):
            gets.append(name)
            if len(gets) == 1:
                started.set()
                assert release.wait(3)
            return body

        link.get_blob_npz = get
        try:
            sha = hashlib.sha256(body).hexdigest()
            link._on_event(json.dumps({"type": "hello_ack", "data": {"blobs": {"wakeword": sha}}}))
            assert started.wait(3)
            link._on_event(json.dumps({"type": "settings_changed", "data": {"settings": {"wakeWord": "시아야"}}}))
            release.set()
            assert settle(lambda: store._local_sha() == sha)
            assert gets == ["wakeword", "wakeword"]
        finally:
            release.set()
            store.close()
            if store._worker is not None:
                store._worker.join(3)


if __name__ == "__main__":
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    tests = [value for name, value in list(globals().items()) if name.startswith("test_")]
    for test in tests:
        output = io.StringIO()
        try:
            with redirect_stdout(output):
                test()
        except BaseException:
            print(output.getvalue())
            raise
    print(f"OK - {len(tests)}/{len(tests)} 호출어 개인화 검사 통과")
