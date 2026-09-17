# -*- coding: utf-8 -*-
"""BE WS 이벤트로 구동하는 호출어·화자 등록.

WakeEnroll은 호출어 샘플을 수집한다. VoiceSession은 낭독 음성을 검증해 화자 프로필을 만들고,
VoiceProfileSync는 BE의 활성 프로필을 로컬에 동기화한다.
"""
import collections
import hashlib
import io
import json
import math
import os
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np

SR = 16000
SENTENCES = [  # 화자 인증 등록 문장 5개 — FE 와 공통 상수. 순서·글자를 바꾸면 FE 도 같이 바꿔야 한다
    "시아야 지금 화면 좀 정리해줘",
    "오늘 날씨가 참 맑고 좋다",
    "이 파일을 다른 폴더로 옮겨줄래",
    "다음 영상으로 넘어가고 음소거 해줘",
    "안녕하세요 저는 이 컴퓨터의 주인입니다",
]
MIN_SPEECH_S = 0.4     # NOTE(튜닝): 짧은 발화 거르기 전용 — 헛기침·"어"·클릭음(말소리 < 0.4 s)만 TOO_SHORT 로
                       # 무른다. "문장을 끝까지 읽었나" 는 여기서 안 본다 — 그건 유사도 게이트와 문장별 quality 몫이다.
                       # 1.5 였다가 내림: speech_s 는 앞 여유분·단어 틈을 안 세서 녹음 길이의 39%(로그 147건 중앙값)만 잡힌다 —
                       # 문장을 2 s 에 읽으면 0.8~1.0 s 라 실제 낭독이 거절됐다. voice_enroll 의 1.5 는 녹음 전체 길이 기준이라 다른 자다
MAX_SPEECH_S = 5.0     # NOTE(튜닝): 말소리 상한. 넘으면 문장 하나가 아니라 두 문장·잡담으로 보고 TOO_LONG. 실측 발화 12건 중 가장 긴
                       # 낭독이 말소리 4.2 s (녹음 5.5 s) 라 5 로 잡았다. 멈춘 시간은 speech_s 가 안 세므로 천천히 읽어도 안 걸린다
QUALITY_MIN_SIM = 0.5  # NOTE(튜닝): 샘플 간 최소 코사인 유사도 하한. voice_enroll 의 "양호" 기준. 미만이면 FE 에 음질 경고
VOICE_MIN_SIM = 0.40   # NOTE(튜닝): 문장 하나가 앞 문장들과 이만큼도 안 닮으면 그 문장만 거절한다. QUALITY_MIN_SIM 보다 낮게 둔다 —
                       # 여기서는 명백한 사고(다른 사람이 읽음·큰 잡음)만 잡고, 미세한 일관성은 5문장을 다 모은 뒤에 본다.
                       # 실측(2026-09-10, 본인 한 명이 같은 자리에서 읽은 5문장): 앞 문장들과 유사도 0.64 / 0.74 / 0.71 / 0.82,
                       # 5문장 일관성 0.78 — 0.40 은 여유 있다. 다른 사람·다른 마이크는 아직 안 쟀다
REJECT_BUDGET = 2      # 등록 1회당 거절 상한 — 목소리 불일치(INCONSISTENT)와 소음(NOISY) 을 따로 센다. 1번 문장이 잘못 녹음되면 그게
                       # 기준이 되어 뒤 문장이 전부 거절되고, 선풍기 소음은 사용자가 못 없앤다. 소진되면 받되 quality 를 "낮음" 으로 보낸다
WAKE_ENROLL_IDLE_S = float(os.environ.get("WAKE_ENROLL_IDLE_S") or 180.0)
# NOTE(튜닝): 마지막 샘플(또는 시작) 뒤 이만큼 조용하면 수집을 접는다. 온보딩을 중간에
# 떠나면 취소 이벤트가 없어(BE·FE 어느 쪽도 안 보낸다) 모든 발화가 등록으로 먹히고
# 음성 명령이 죽는다. 5개를 채우는 사람은 몇 초 간격으로 말하므로 3분이면 넉넉하다.
WAKE_TOTAL = 5         # 온보딩 "시아야" 부르기 샘플 수 — FE 진행바의 total 과 같은 값. 10 이었다가 5 로 줄임 (2026-09-10)
WAKE_MIN_SIM = 0.30    # ponytail: 임시값. 호출어 교차 화자 실측 후 조정한다
REJECT_CODES = {"TOO_SHORT", "TOO_LONG", "NOISY", "INCONSISTENT", "MISMATCH"}
                     # 두 이벤트(wakeword_rejected · voice_sentence_rejected)의 확정 code 어휘, BE 프로토콜 §4 와 같은 값
REJECT_REASONS = {   # 품질 판정 사유 → FE 에 보여 줄 문구
    "TOO_SHORT": "너무 짧게 들렸어요. 호출어를 끝까지 불러주세요.",
    "TOO_LONG": "너무 길게 들렸어요. 호출어만 불러주세요.",
    "NOISY": "주변이 시끄러워요. 조용한 곳에서 다시 불러주세요.",
    "LOW_QUALITY": "또렷하게 들리지 않았어요. 마이크에 조금 더 가까이, 호출어만 불러주세요.",
}
WAKE_DEFAULT_WORD = "시아야"   # 설정(settings.wakeWord)이 오기 전에 쓰는 기본 호출어 — brain.WAKE_WORD 와 같은 값
WAKE_UPLOAD_RETRY_S = 5   # 업로드가 실패하면 이만큼 쉬었다가 다시 보낸다 — 그 사이 더 새 작업이 오면 그것부터
WAKE_UPLOAD_TRIES = 3     # 같은 본문을 보낼 최대 횟수. 넘으면 서버는 이전 상태로 남는다 (로그로 알린다)
VOICE_SYNC_RETRY_S = 1.0  # 활성 보이스 받기가 실패하면 이만큼 쉬었다가 같은 참조를 한 번만 다시 받는다 —
                          # BE 가 voice_changed 를 DB 커밋 전에 보내 첫 GET 이 500 으로 끝난 실측(2026-09-17)


def log_rx(type_, data):
    """BE 가 보낸 화자 등록 이벤트를 한 줄로 남긴다 — 실기동 때 무엇이 언제 왔는지 눈으로 확인하려고.
    조건이 안 맞아 무시되는 이벤트도 찍힌다. 그래야 "안 왔다" 와 "왔는데 무시했다" 를 구분할 수 있다."""
    print(f"[BE←] {type_} {json.dumps(data, ensure_ascii=False)}")


def clear_voice_cache(speaker, profile_path):
    """활성 음성 캐시만 지운다 — 보정·제스처 파일과 등록 샘플은 건드리지 않는다."""
    path = Path(profile_path)
    if path.exists():
        print(f"[보이스 동기화] 서버에 사용 중인 목소리가 없어 로컬 프로필을 지운다 — {path}")
    path.unlink(missing_ok=True)
    speaker.apply_profile(None, speaker.default_threshold)


MIC_PREVIEW_HZ = 20        # BE 권장 10~30 Hz (§5.5). 블록당 1개면 33 Hz 인데 파형이 얻는 건 없고 메시지만 는다.
MIC_PREVIEW_FLOOR_DB = -60.0   # 이 아래는 무음(0.0). 레벨 미터의 통상적인 바닥.


def mic_level(rms):
    """int16 rms → 0.0~1.0. 선형으로 32768 로 나누면 보통 말소리가 0.03 언저리라 막대가 안 보인다 —
    레벨 미터는 dBFS 로 그린다. 바닥 -60 dBFS (말소리 rms 1000 ≈ 0.49, VAD 시작 임계 350 ≈ 0.34)."""
    if rms <= 0:
        return 0.0
    db = 20.0 * math.log10(min(float(rms), 32768.0) / 32768.0)
    return max(0.0, min(1.0, (db - MIC_PREVIEW_FLOOR_DB) / -MIC_PREVIEW_FLOOR_DB))


class MicPreview:
    """상시 감지 루프가 이미 재 둔 입력 레벨을 BE(mic_preview_*)로 흘린다 (프로토콜 §5.5).

    등록 화면에서 "내 목소리가 들어가고 있나"를 말하는 동안 보여 주는 파형이다. 등록 흐름은
    순번만 알려줄 뿐 말하는 중엔 아무 신호가 없어서, 판독 결과가 뜰 때까지 마이크가 살았는지 모른다.

    마이크를 새로 열지 않는다 — VAD 가 블록마다 계산해 둔 rms 를 읽어 보내기만 하므로 미리보기
    중에도 호출어 감지는 그대로 돈다. 카메라 판(gesture_be.GesturePreview)과 달리 인코딩이 없어
    워커 스레드도 큐도 없고, 준비 단계가 없어 STARTING 없이 바로 READY 다.
    등록이 시작돼도 끊지 않는다 — 파형을 보여주려는 때가 바로 낭독 중이다 (카메라와 반대).
    """

    def __init__(self, link):
        self.link = link
        self.active = False
        self._seq = 0
        self._last_sent = 0.0

    def start(self):
        self.active = True
        self._seq = 0
        self._last_sent = 0.0
        self.link.send_event("mic_preview_state", {"phase": "READY"})

    def stop(self):
        if not self.active:
            return
        self.active = False
        self.link.send_event("mic_preview_state", {"phase": "STOPPED"})

    def tick(self, rms, now):
        """메인 루프에서 매 회 호출. 보낼 때가 아니면 즉시 돌아간다."""
        if not self.active or now - self._last_sent < 1.0 / MIC_PREVIEW_HZ:
            return
        self._last_sent = now
        self._seq += 1
        # 한 메시지가 진폭 하나다 — 배열로 묶으면 묶은 만큼 파형이 늦게 움직인다 (§5.5).
        self.link.send_event("mic_preview_level",
                             {"seq": self._seq, "level": mic_level(rms), "tsMs": int(now * 1000)})


class VoiceProfileSync:
    """다운로드는 워커, 적용은 메인 루프. 늦게 받은 이전 프로필은 적용 전에 버린다."""

    def __init__(self, speaker, profile_path):
        self.speaker = speaker
        self.path = Path(profile_path)
        self.link = None
        self._condition = threading.Condition()
        self._desired = object()  # 아직 수신하지 않음 — 명시적 null과 구분한다.
        self._applied = object()
        self._generation = 0
        self._queued = self._busy = self._closed = False
        self._pending = None
        self._worker = None

    def on_changed(self, ref):
        """전체 설정의 blobs.voice와 voice_changed가 같은 최신 요청을 갱신한다."""
        if ref is not None:
            if (not isinstance(ref, dict) or type(ref.get("id")) is not int or ref["id"] <= 0
                    or not isinstance(ref.get("sha256"), str) or len(ref["sha256"]) != 64
                    or any(c not in "0123456789abcdefABCDEF" for c in ref["sha256"])):
                print("[보이스 동기화] 잘못된 프로필 참조 — 기존 프로필 유지")
                return
            ref = (ref["id"], ref["sha256"].lower())
        with self._condition:
            if self._closed:
                return
            if ref == self._desired and (self._queued or self._busy or self._pending is not None):
                return
            if ref != self._desired:
                self._generation += 1
                self._desired = ref
            self._pending = None
            if ref is None:
                # 이전 HTTP 응답을 기다리지 않고 다음 메인 루프에서 삭제한다.
                self._queued = False
                self._pending = (self._generation, None, None)
            else:
                self._queued = True
                if self._worker is None:
                    self._worker = threading.Thread(target=self._run, daemon=True)
                    self._worker.start()
            self._condition.notify_all()

    def _prepare(self, ref):
        _, digest = ref
        try:
            body = self.path.read_bytes()
            if hashlib.sha256(body).hexdigest() != digest:
                raise ValueError("로컬 해시 불일치")
            profile = self.speaker.read_profile(io.BytesIO(body), self.speaker.default_threshold)
            return body, profile
        except Exception:  # 손상된 ZIP·객체 배열도 로컬 캐시 실패로 보고 서버에서 다시 받는다.
            pass
        body = self.link.get_voice_npz()
        if hashlib.sha256(body).hexdigest() != digest:
            raise ValueError("다운로드한 보이스의 sha256이 수신 참조와 다릅니다")
        return body, self.speaker.read_profile(io.BytesIO(body), self.speaker.default_threshold)

    def _run(self):
        retried = None   # 한 번 다시 받아 본 참조 — 같은 참조를 두 번 재시도하지 않는다
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._closed or self._queued)
                if self._closed:
                    return
                ref = self._desired
                self._queued, self._busy = False, True
            try:
                prepared = self._prepare(ref)
                retried = None
                with self._condition:
                    # ID만 바뀐 최신 요청에도 이미 검증한 동일 해시의 파일을 쓸 수 있다.
                    if not self._closed and self._desired is not None and self._desired[1] == ref[1]:
                        self._pending = (self._generation, self._desired, prepared)
                        self._queued = False
            except Exception as exc:
                print(f"[보이스 동기화] 실패 — 기존 프로필 유지: {exc}")
                with self._condition:
                    if not self._closed and self._desired == ref and retried != ref:
                        # 같은 참조를 잠시 뒤 한 번만 다시 받는다. 기다리는 동안 새 참조가 오면 그쪽이 먼저다
                        retried = ref
                        print(f"[보이스 동기화] {VOICE_SYNC_RETRY_S:g} s 뒤 다시 받는다")
                        self._condition.wait(VOICE_SYNC_RETRY_S)
                        if not self._closed and self._desired == ref:
                            self._queued = True
            finally:
                with self._condition:
                    self._busy = False
                    self._condition.notify_all()

    def apply_pending(self, reset_audio):
        """검증을 마친 최신 파일만 교체한다. 네트워크·임베딩 중에는 잠금을 잡지 않는다."""
        with self._condition:
            pending, self._pending = self._pending, None
            if self._closed or pending is None or pending[0] != self._generation:
                return False
            _, ref, prepared = pending
            temp_path = None
            try:
                if ref is None:
                    changed = (self._applied is not None or self.path.exists()
                               or self.speaker.enrolled or self.speaker.profile_id is not None)
                    if changed:
                        reset_audio()
                    clear_voice_cache(self.speaker, self.path)
                    self._applied = None
                    return changed
                body, (centroid, threshold) = prepared
                profile_id, digest = ref
                try:
                    same_file = self.path.read_bytes() == body
                except OSError:
                    same_file = False
                old = self.speaker.snapshot()
                changed = (old[2:] != ref or old[0] is None or old[1] != threshold
                           or not np.array_equal(old[0], centroid))
                if not same_file:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(dir=self.path.parent, suffix=".npz", delete=False) as f:
                        temp_path = Path(f.name)
                        f.write(body)
                if changed:
                    reset_audio()  # 실패할 수 있는 콜백은 기존 정상 파일을 교체하기 전에 끝낸다.
                if temp_path is not None:
                    os.replace(temp_path, self.path)
                if changed:
                    self.speaker.apply_profile(centroid, threshold, profile_id, digest)
                    print(f"[보이스 동기화] 활성 프로필 적용 id={profile_id}")
                self._applied = ref
                return changed
            except Exception as exc:
                print(f"[보이스 동기화] 적용 실패: {exc}")
                return False
            finally:
                if temp_path is not None:
                    try:
                        temp_path.unlink(missing_ok=True)
                    except OSError as exc:
                        print(f"[보이스 동기화] 임시 파일 정리 실패: {exc}")

    def close(self):
        with self._condition:
            self._closed = True
            self._queued = False
            self._pending = None
            self._condition.notify_all()


class VoiceSession:
    def __init__(self, link, speaker, profile_path):
        self.link = link                    # AgentLink (WS 발신·rt) 또는 스텁
        self.speaker = speaker              # SpeakerVerifier — 등록 임베딩·centroid 계산용
        self.profile_path = str(profile_path)
        self.active = False
        self.started_at = 0.0               # 이 수집이 시작된 시각 — 두 수집이 겹치면 나중에 시작한 쪽이 발화를 받는다
        self.tempId = None
        self.total = len(SENTENCES)
        self._n = 0                         # 수집 중인 문장(0=대기)
        self._samples = {}                  # n -> int16 오디오
        self._embs = {}                     # n -> 임베딩. 문장을 받을 때 그 자리에서 채운다
        self._rejects = 0                   # 이번 등록에서 목소리 불일치로 무른 횟수 (REJECT_BUDGET 까지)
        self._noisy = 0                     # 이번 등록에서 소음으로 무른 횟수 (REJECT_BUDGET 까지)
        self._last_reject = None            # (n, 임베딩) — 직전에 목소리 불일치로 무른 시도. 같은 문장 두 시도를 견주는 데 쓴다
        self._suspect = set()               # 찌그러진 것으로 의심돼 비교 기준에서 뺀 문장 번호
        self._collect_t = 0.0               # 마지막 voice_collect 시각 — 그보다 먼저 시작된 발화는 이전 지시의 것이다
        self._warn_pending = False          # 음질 경고를 보내고 사용자 선택을 기다리는 중 — voice_finalize 는 이때만 받는다
        self._warned = False                # 이번 등록에서 음질 경고를 보냈다 — _finish 의 임시 가드
        self.epoch = 0                      # 수집 회차 — 재녹음은 tempId 가 그대로라, 늦게 끝난 이전 업로드를 이 값으로 가린다
        self._results = []                  # 끝난 업로드 — 워커가 넣고 메인 루프가 apply_uploads() 로 꺼낸다
        self._jobs = collections.deque()    # 올릴 것들 — 받은 순서대로 하나씩. 겹쳐 올리면 늦게 끝난 쪽이 덮어쓴다
        self._jobs_cv = threading.Condition()
        self._uploading = False             # 워커가 올리는 중
        self._upload_worker = None          # 업로드 워커 (하나만 둔다)
        self._preload = None                # 모델 프리로드 스레드

    def _tx(self, type_, data):
        """BE 로 나가는 화자 등록 이벤트는 전부 여기를 지난다 — 보낸 것도 한 줄씩 남긴다."""
        print(f"[BE→] {type_} {json.dumps(data, ensure_ascii=False)}")
        self.link._send({"type": type_, "data": data})

    # ── BE 이벤트 진입점 (assistant 메인 루프에서 on_utter 와 순서대로 처리) ──
    def on_start(self, tempId, total=None):
        log_rx("voice_reg_start", {"tempId": tempId, "total": total})
        self.tempId, self.active, self.started_at = tempId, True, time.monotonic()
        self.total = int(total or len(SENTENCES))
        self._samples, self._embs, self._n, self._rejects, self._noisy = {}, {}, 0, 0, 0
        self._last_reject, self._suspect, self._warn_pending, self._warned = None, set(), False, False
        self.epoch += 1
        # 모델(첫 로드 12 s)은 낭독하는 동안 미리 — 마무리 때 메인 루프가 멈추지 않게. 이미 로드됐으면 즉시 끝난다
        self._preload = threading.Thread(target=self.speaker._model, daemon=True)
        self._preload.start()
        self._tx("voice_ready", {"tempId": tempId})

    def on_collect(self, tempId, n):
        log_rx("voice_collect", {"tempId": tempId, "n": n})
        if not self.active or tempId != self.tempId or not n:
            return
        self._n = int(n)
        self._collect_t = time.monotonic()  # 이 시각 전에 시작된 발화는 이전 지시의 것 — on_utter 가 버린다
        self._warn_pending = False          # 다시 읽기로 답했다 — 앞선 경고에 대한 "그대로 진행" 이 늦게 와도 받지 않는다
        self.epoch += 1                    # 새 회차 — 진행 중이던 업로드의 결과는 이 문장에 반영하지 않는다
        # n번을 다시 읽으라는 뜻이니 n번과 그 뒤에 받아 둔 샘플은 버린다 — 안 버리면 "다시 녹음"(n=1) 때
        # 앞서 읽은 2·3번이 남아, 새 1번 발화 하나만으로 "문장이 다 모였다" 가 되어 등록이 일찍 끝난다
        keep = {k: v for k, v in self._samples.items() if k < self._n}
        dropped = len(self._samples) - len(keep)
        self._samples = keep
        self._embs = {k: v for k, v in self._embs.items() if k < self._n}
        self._suspect = {k for k in self._suspect if k < self._n}
        if self._last_reject and self._last_reject[0] != self._n:
            self._last_reject = None        # 다른 문장으로 넘어갔으면 직전 거절은 뜻이 없다
        if not self._embs:
            self._rejects = self._noisy = 0  # 앞 문장이 다 사라지면 비교 기준도 사라진다 — 거절 예산도 되돌린다
        text = SENTENCES[self._n - 1] if self._n <= len(SENTENCES) else "?"
        if dropped:
            print(f"[화자 등록] 문장 {self._n}/{self.total} 재수집 — 이전 샘플 {dropped}개 폐기")
        print(f"[화자 등록] 문장 {self._n}/{self.total}: \"{text}\"")

    def on_finalize(self, tempId):
        log_rx("voice_finalize", {"tempId": tempId})
        if not self.active or tempId != self.tempId:
            return
        if not self._warn_pending:
            # 음질 경고에 대한 "그대로 진행" 답이다 — 경고 전이거나 이미 다시 녹음에 들어갔으면 늦게 온 옛 답이다.
            # 지금 모으는 중인 문장으로 등록을 끝내 버리면 안 된다
            print("[화자 등록] 음질 경고 대기 상태가 아니라 마무리 지시를 무시한다")
            return
        self._warn_pending = False
        self._finish(forced=True)   # 같은 경고로 다시 막으면 등록이 끝나지 않는다

    def on_cancel(self, tempId):
        log_rx("voice_reg_cancel", {"tempId": tempId})
        if not self.active or tempId != self.tempId:
            return
        self.active, self._n, self._samples, self._embs, self._rejects = False, 0, {}, {}, 0
        self._last_reject, self._suspect, self._warn_pending = None, set(), False
        self.epoch += 1
        print("[화자 등록] 중단 — 이전 프로필 유지")

    def on_registered(self, prof_id, is_active):
        log_rx("voice_registered", {"id": prof_id, "active": is_active})
        # 프로필 확정. 활성 여부는 BE 가 정한다 — 활성 리로드는 voice_changed 에서만
        self.active = False
        print(f"[화자 등록] 프로필 확정 id={prof_id} active={is_active}")

    def on_changed(self, data):
        """활성 교체는 전체 설정 수신과 같은 동기화 경로로 보낸다."""
        log_rx("voice_changed", data)
        if self.link.voice_sync is not None:
            self.link.voice_sync.on_changed(data)

    # ── 메인 루프가 VAD 발화마다 호출 (등록 중엔 brain 대신 여기로) ──
    def on_utter(self, audio_i16, t_utter=None):
        from brain import wav_bytes

        if not self.active:
            return
        if self._n == 0:
            # 다섯 문장을 다 읽고 확정을 기다리는 중이다. 명령으로 넘기지 않는 게 맞지만, 왜 안 먹는지는 남겨 둔다
            print("[화자 등록] 확정 전이라 발화를 받지 않는다 — 등록을 마치거나 중단하세요")
            return
        if t_utter is not None and t_utter < self._collect_t:
            # "이 문장 다시" 를 누르기 직전에 시작한 낭독 — 받으면 방금 무르려던 그 발화로 문장이 넘어간다.
            # VAD 는 말이 끝나고 0.55 s 뒤에야 발화를 넘겨주므로 이 순서가 실제로 생긴다
            print(f"[화자 등록] 문장 {self._n} 지시보다 먼저 시작된 발화 — 버리고 다시 기다린다")
            return
        from brain import noise_level, speech_s

        n = self._n
        spoken = speech_s(audio_i16)
        if spoken < MIN_SPEECH_S:
            self._reject(n, "TOO_SHORT", "너무 짧게 들렸어요. 문장을 끝까지 읽어주세요.", f"말소리 {spoken:.1f} s")
            return
        if spoken > MAX_SPEECH_S:
            self._reject(n, "TOO_LONG", "너무 길게 들렸어요. 화면의 문장 하나만 읽어주세요.", f"말소리 {spoken:.1f} s > {MAX_SPEECH_S}")
            return
        audio = np.asarray(audio_i16, dtype=np.int16)
        noise = noise_level(audio)
        # 임베딩 전에 거른다 — 시끄러운 녹음을 뽑아 봐야 뒤 문장의 비교 기준만 흐려진다
        if noise == "높음" and self._noisy < REJECT_BUDGET:
            self._noisy += 1
            self._reject(n, "NOISY", "주변이 시끄러워요. 조용한 곳에서 다시 읽어주세요.", f"소음 높음, 거절 {self._noisy}/{REJECT_BUDGET}")
            return
        # 임베딩은 문장을 받은 자리에서 바로 뽑는다 — 5개를 마지막에 몰아 뽑으면 그만큼 마무리가 늦고,
        # 앞 문장과 닮았는지도 지금 봐야 사용자가 그 문장을 바로 다시 읽을 수 있다
        if self._preload is not None:
            self._preload.join()            # 첫 문장이면 모델 로드(첫 12 s)를 여기서 기다린다
            self._preload = None
        try:
            emb = self.speaker.embed(audio)
            if not np.isfinite(emb).all():
                raise ValueError("임베딩에 NaN")
        except Exception as e:
            # code 없이 사유만 — 계약 어휘에 맞는 코드가 없고 code 는 선택 필드다. 모델이 계속 실패하면 사용자는 매번 이 문구를 보고
            # "중단" 으로 나간다 — AI 가 등록을 스스로 끝내는 이벤트는 계약에 없다
            self._reject(n, None, "목소리 분석에 실패했어요. 잠시 후 다시 읽어주세요.", f"임베딩 실패 {e}")
            return
        sim = None                          # 앞 문장들과 유사도 — 1번 문장은 비교 대상이 없다
        ref = [e for k, e in self._embs.items() if k not in self._suspect]   # 의심 문장은 기준에서 뺀다
        if ref:
            centroid, _ = self.speaker.centroid_of_embs(ref)
            sim = float(emb @ centroid)
            if sim < VOICE_MIN_SIM and self._rejects < REJECT_BUDGET:
                last = self._last_reject
                agree = float(emb @ last[1]) if last and last[0] == n else None
                if len(ref) == 1 and agree is not None and agree >= QUALITY_MIN_SIM:
                    # 같은 문장을 두 번 읽었는데 둘은 닮았고 앞 문장 하나와만 다르다 — 범인은 앞 문장(찌그러진 앵커)이다.
                    # 이 문장을 받고 앞 문장은 이후 기준에서 뺀다. 프로필에 넣을지는 _finish 가 다섯 개를 놓고 다시 본다
                    bad = next(k for k in self._embs if k not in self._suspect)
                    self._suspect.add(bad)
                    print(f"[화자 등록] 문장 {n} 두 시도끼리 유사도 {agree:.2f} ≥ {QUALITY_MIN_SIM}, 앞 문장 {bad}과만 다름({sim:.2f}) "
                          f"— {bad}번을 의심해 기준에서 뺀다")
                else:
                    self._rejects += 1
                    self._last_reject = (n, emb)
                    self._reject(n, "INCONSISTENT", "앞 문장과 목소리가 다르게 들려요. 같은 분이 조용한 곳에서 다시 읽어주세요.",
                                 f"앞 문장들과 유사도 {sim:.2f} < {VOICE_MIN_SIM}, 거절 {self._rejects}/{REJECT_BUDGET}")
                    return
        self._last_reject = None
        self._samples[n], self._embs[n] = audio, emb
        # 이 문장의 판독 결과 — 거절 예산이 떨어져 받아 준 문장도 여기서 "낮음" 이 되어 사용자가 그 자리에서 다시 읽을 수 있다
        quality = "양호" if (sim is None or sim >= QUALITY_MIN_SIM) and noise != "높음" else "낮음"
        # 통과 로그 — 실측 때 VOICE_MIN_SIM·MIN_SPEECH_S 를 맞추는 근거. 예산 소진 뒤 통과한 문장도 유사도가 남는다
        print(f"[화자 등록] 문장 {n} 통과 — 말소리 {spoken:.1f} s, "
              + (f"앞 문장들과 유사도 {sim:.2f}" if sim is not None else "첫 문장(비교 없음)")
              + f", 품질 {quality}, 소음 {noise}")
        if all(k in self._samples for k in range(1, self.total + 1)):
            self._n = 0
            self._tx("voice_progress", {"tempId": self.tempId, "n": n})
            self._finish()   # 마지막 문장 — 샘플과 npz 를 여기서 함께 올린다
            return
        # 방금 읽은 문장만 올리고 판독 결과를 보낸다 — FE 가 문장마다 그 녹음을 들어 보고 다시 읽을지 정한다.
        # npz 는 아직 안 올린다: 다섯 문장을 다 모으기 전 npz 가 서버에 있으면 그것만으로 프로필이 확정될 수 있다
        self._n = 0
        self._start_upload(wav_bytes(audio), None, round(len(audio) / SR, 1), quality, noise, n, False)

    # ── 내부 ──
    def _reject(self, n, code, reason, why):
        """문장 하나를 무르고 사유를 보낸다. self._n 은 그대로 둔다 — 순번을 진행하지 않고 같은 문장을 계속 기다린다.

        code 는 REJECT_CODES 의 TOO_SHORT·TOO_LONG·NOISY·INCONSISTENT 만 보내고, 목소리 분석 실패·저장 실패는 reason 만 보낸다.
        """
        print(f"[화자 등록] 문장 {n} 거절({code or '사유만'}) — {why}, 다시 기다린다")
        data = {"tempId": self.tempId, "n": n, "reason": reason}
        if code in REJECT_CODES:
            data["code"] = code             # 어휘 밖이거나 없으면 키 자체를 넣지 않는다 — BE 계약 (FE 는 reason 으로 폴백)
        self._tx("voice_sentence_rejected", data)

    def _finish(self, forced=False):
        """다 모은 문장으로 프로필을 만든다. 음질이 미달이면 올리지 않고 voice_quality_warn 으로 사용자에게 묻는다.
        forced 는 그 물음에 "그대로 진행" 이 돌아온 경우(voice_finalize)다 — 그때는 묻지 않고 마무리한다."""
        from brain import noise_level, wav_bytes

        keys = sorted(self._embs)
        if not keys:
            self._n = 1
            self._collect_t = time.monotonic()
            self._reject(1, None, "아직 문장을 하나도 받지 못했어요. 화면의 문장을 읽어주세요.", "수집된 문장 없음")
            return
        # 혼자 튀는 문장 하나는 프로필 평균에서 뺀다 — 찌그러진 1번이 기준이 됐던 경우가 여기서 걸러진다.
        # 각 문장을 나머지 평균과 견줘, 하나만 VOICE_MIN_SIM 아래이고 나머지는 전부 QUALITY_MIN_SIM 이상일 때만 뺀다.
        # 둘 이상 튀면 어느 쪽이 본인인지 모르니 그대로 두고 voice_captured 의 quality 를 "낮음" 으로 보낸다
        use = keys
        if len(keys) >= 3:
            loo = {k: float(self._embs[k] @ self.speaker.centroid_of_embs([self._embs[j] for j in keys if j != k])[0]) for k in keys}
            low = [k for k in keys if loo[k] < VOICE_MIN_SIM]
            if len(low) == 1 and all(loo[k] >= QUALITY_MIN_SIM for k in keys if k != low[0]):
                use = [k for k in keys if k != low[0]]
                print(f"[화자 등록] 문장 {low[0]} 이 나머지와 안 닮음(유사도 {loo[low[0]]:.2f}) — 프로필 평균에서 빼고 {len(use)}문장으로 만든다")
        centroid, min_sim = self.speaker.centroid_of_embs([self._embs[k] for k in use])
        wav = self._samples[keys[-1]]  # 마지막 문장도 해당 녹음만 재생한다.
        noise = noise_level(np.concatenate([self._samples[k] for k in keys]))  # 등록 소음은 모든 문장으로 판정한다.
        quality = "양호" if min_sim >= QUALITY_MIN_SIM else "낮음"
        print(f"[화자 등록] 샘플 일관성 {min_sim:.2f} → {quality}, 소음 {noise}")
        self._n = 0  # finalize 가 수집 중에 와도 마무리 뒤 발화를 새 문장으로 받지 않는다.
        if not forced and not self._warned and (quality == "낮음" or noise == "높음"):
            # 이대로 만든 프로필은 본인도 자주 거부된다 — 올리기 전에 묻고 "그대로 진행"(voice_finalize) 이 오면 마무리한다.
            # NOTE(한계): 묻는 것은 등록당 한 번뿐이다(_warned). 온보딩 화면엔 "그대로 진행" 이 없고 "다시 녹음" 은 마지막
            # 문장만 다시 받아(실측 2026-09-14), 매번 물으면 시끄러운 곳에서는 등록을 못 끝낸다. FE 가 고쳐지면 이 가드를 뺀다
            reason = ("주변이 시끄러워 목소리가 잘 담기지 않았어요. 조용한 곳에서 다시 녹음하시겠어요?" if noise == "높음"
                      else "문장마다 목소리가 다르게 들렸어요. 다시 녹음하시겠어요?")
            print("[화자 등록] 음질 미달 — 업로드를 멈추고 사용자 선택을 기다린다")
            self._warned = self._warn_pending = True
            self._tx("voice_quality_warn", {"tempId": self.tempId, "reason": reason, "noise": noise})
            return
        self._start_upload(wav_bytes(wav), self.speaker.npz_bytes(centroid),
                           round(len(wav) / SR, 1), quality, noise, keys[-1], True)

    def _start_upload(self, wav, npz, dur, quality, noise, n, final):
        """업로드를 워커에 맡기고 메인 루프를 돌려준다 — PUT 한 번이 최대 15 s 라 그동안 카메라·발화 처리가 멈춘다.

        결과는 apply_uploads() 가 꺼내므로 올리는 동안 온 "다시 녹음"·"중단" 이 먼저 처리된다.
        올릴 대상과 회차는 여기서 고정한다 — 워커가 늦게 돌아도 그때의 등록에 올린다."""
        with self._jobs_cv:
            self._jobs.append((self.tempId, self.epoch, wav, npz, dur, quality, noise, n, final))
            if self._upload_worker is None or not self._upload_worker.is_alive():
                self._upload_worker = threading.Thread(target=self._run_uploads, daemon=True)
                self._upload_worker.start()
            self._jobs_cv.notify_all()

    def _run_uploads(self):
        """업로드 워커 — 받은 순서대로 하나씩 올린다. 겹쳐 올리면 늦게 끝난 이전 PUT 이 방금 올린 녹음을 덮어쓴다."""
        while True:
            with self._jobs_cv:
                if not self._jobs:
                    self._uploading = False
                    self._jobs_cv.notify_all()
                    if not self._jobs_cv.wait_for(lambda: bool(self._jobs), timeout=60):
                        return                      # 한동안 할 일이 없으면 워커를 접는다
                temp_id, epoch, wav, npz, dur, quality, noise, n, final = self._jobs.popleft()
                self._uploading = True
            if epoch != self.epoch or not self.active:
                print("[화자 등록] 이전 회차의 업로드 — 올리지 않습니다")   # 올리면 지금 녹음을 덮어쓴다
                continue
            ok = self._upload(temp_id, wav, npz)
            self._results.append((temp_id, epoch, ok, dur, quality, noise, n, final))

    def apply_uploads(self):
        """메인 루프가 매 프레임 부른다 — 끝난 업로드의 판독 결과·완료·실패 안내를 여기서 보낸다."""
        while self._results:
            temp_id, epoch, ok, dur, quality, noise, n, final = self._results.pop(0)
            if epoch != self.epoch or not self.active:
                print("[화자 등록] 이전 회차의 업로드 완료 — 새 회차에 반영하지 않습니다")
                continue
            if ok:
                if not final:
                    # 방금 읽은 문장의 판독 결과 — 서버에 녹음이 있어야 FE 가 들어 보고 "다음" 을 누를 수 있다
                    self._tx("voice_progress", {"tempId": temp_id, "n": n})
                self._tx("voice_captured", {"tempId": temp_id, "durationSec": dur,
                                            "quality": quality, "noise": noise})
                continue
            # 서버에 녹음이 없으면 통과로 세지 않고 그 문장을 다시 읽게 한다 — 계약에 "녹음 없이 업로드만 다시" 는 없다.
            # 앞서 받아 둔 문장은 그대로 두므로 그 문장만 다시 읽으면 이어서 진행된다
            if not final:
                self._samples.pop(n, None)
                self._embs.pop(n, None)
            self._n = n
            self._reject(n, None, "녹음을 저장하지 못했어요. "
                         + ("마지막 문장을 한 번 더 읽어주세요." if final else "문장을 한 번 더 읽어주세요."),
                         "마무리 업로드 실패" if final else "샘플 업로드 실패")

    def _upload(self, temp_id, wav, npz=None):
        """문장 녹음(+마무리면 npz)을 temp_id 등록에 올린다. 대상은 넘겨받는다 — 도중에 새 등록이 시작돼도 거기 쓰지 않는다.

        다 성공했을 때만 True — 서버에 녹음이 없는데 완료를 알리면 FE 는 재생도 확정도 못 하는 화면에서 멈춘다."""
        base = f"http://127.0.0.1:{self.link.rt['port']}/api/agent/voices/{temp_id}"
        try:
            self._put(base + "/sample", wav, "audio/wav")
            if npz is not None:
                self._put(base + "/npz", npz, "application/octet-stream")
        except Exception as e:
            print(f"[화자 등록] 업로드 실패: {e}")
            return False
        return True

    @staticmethod
    def _put(url, body, ctype):
        req = urllib.request.Request(url, data=body, method="PUT")
        req.add_header("Content-Type", ctype)
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"[BE REST] PUT {url} {ctype} ({len(body)} B) → {r.status}")


class WakeTemplateStore:
    """호출어 템플릿 보관소 — 로컬 파일과 BE blob(`wakeword`)의 등록·동기화를 다룬다.

    BE에는 호출어 NPZ 한 개를 저장한다. 등록자는 템플릿의 목소리 임베딩으로 확인하며 보이스 프로필 번호와 묶지 않는다.
    generation은 로컬 상태 변경을, 쓰기 순번은 업로드 순서를 구분한다.
    다운로드·업로드는 각각 워커에서 처리하며, 오래된 작업은 적용하지 않는다.
    """

    def __init__(self, path, link=None, default_word=WAKE_DEFAULT_WORD):
        self.path = Path(path)
        self.link = link
        self.default_word = default_word
        self.setting_word = None     # settings.wakeWord — BE 설정이 오기 전에는 None
        self.current = None          # WakeTemplate 또는 None
        self.load_error = None       # 파일이 있는데 못 읽은 사유 (있으면 "미등록" 이 아니라 "재등록 필요")
        self.generation = 0
        self.dropped = 0             # 만료돼 보내지 않은 서버 쓰기 수 — 폐기가 실제로 일어났는지 보려고 센다
        self.put = VoiceSession._put  # REST 업로드 — 테스트에서 바꿔 끼운다
        self._lock = threading.Condition()
        self._put_lock = threading.Lock()   # PUT을 하나씩 보내 저장 순서를 유지한다
        self._write_seq = 0          # 서버 쓰기 순번. 새 예약이 생기면 앞선 예약은 만료다
        self._want = None            # 서버가 알린 sha256 (없으면 아직 못 받음)
        self._queued = False
        self._worker = None
        self._upload = None          # (순번, 본문, 보낸 횟수) — 올릴 것 하나만 (최신만 의미 있다)
        self._writers = 0            # 진행 중인 서버 쓰기 수 — 등록의 직접 쓰기도 포함한다
        self._sent_sha = None        # 업로드한 파일의 알림을 다시 다운로드하지 않도록 저장한 해시
                                     # 로컬 저장이 끝나거나 실패하면 지운다
        self._uploader = None
        self._closed = False
        self.load()

    # ── 판정용 스냅샷 ──
    def snapshot(self):
        """(설정 호출어, 템플릿, generation) — 한 판정이 끝까지 같은 상태를 보게 한다."""
        with self._lock:
            return self.wake_word(), self.current, self.generation

    def still_current(self, generation):
        """호출어 판정 도중 설정이나 템플릿이 바뀌었는지 확인한다."""
        with self._lock:
            return not self._closed and generation == self.generation

    # ── 호출어 문자열 ──
    def wake_word(self):
        """지금 적용 중인 호출어 — BE 설정이 왔으면 그 값, 아니면 기본값."""
        return self.setting_word or self.default_word

    def on_settings(self, settings):
        """호출어 설정 반영. 등록 당시 문자열과 다르면 matches_setting에서 사용을 막는다."""
        if not isinstance(settings, dict) or "wakeWord" not in settings:
            return False
        word = settings["wakeWord"]
        if not isinstance(word, str) or not word.strip() or word == self.setting_word:
            return False
        with self._lock:
            self.setting_word = word
            self.generation += 1          # 판정 중인 발화는 이 설정으로 다시 봐야 한다
            template = self.current
        from brain import WAKE_MODEL_WORD

        # 고정 모델과 설정 호출어가 다르면 세션이 열리지 않으므로 원인을 출력한다.
        print(f'[BE←] settings.wakeWord "{word}"'
              + ("" if word == WAKE_MODEL_WORD else
                 f' — 고정 모델 문구 "{WAKE_MODEL_WORD}" 와 달라 세션이 열리지 않습니다'
                 " (사용자 지정 호출어는 아직 지원하지 않습니다)"))
        if template is not None and not template.matches_setting(word):
            print(f"[호출어 템플릿] 설정이 \"{word}\" 로 바뀌었는데 템플릿은 \"{template.wake_text}\" 로 등록돼 있습니다 "
                  "— 새 호출어로 다시 등록해야 세션이 열립니다")
        return True

    # ── 로컬 파일 ──
    def load(self):
        """로컬 템플릿 읽기. 파일이 없으면 미등록, 있는데 못 읽으면 손상 — 둘을 구분해 둔다."""
        from speaker import WakeTemplate

        try:
            with open(self.path, "rb") as f:
                template = WakeTemplate.read(f)
        except FileNotFoundError:
            self.current, self.load_error = None, None
            return
        except Exception as e:
            self.current, self.load_error = None, f"{type(e).__name__}: {e}"
            print(f"[호출어 템플릿] 읽지 못했습니다({self.load_error}) — 다시 등록해야 합니다")
            return
        self.current, self.load_error = template, None
        print(f"[호출어 템플릿] 로컬 적용 — 호출어 \"{template.wake_text}\", 기준 {template.base_n}개")

    def _prepare(self, template):
        """NPZ를 임시 파일에 저장 → (본문, 임시 경로). 파일 준비 중에는 잠금을 잡지 않는다."""
        body = template.npz_bytes()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.path.parent, suffix=".npz", delete=False) as f:
            temp = Path(f.name)
            f.write(body)
        return body, temp

    def commit(self, template, why, generation=None, want=None):
        """검증까지 끝난 템플릿을 확정 → (본문, 새 generation, 서버 쓰기 순번) 또는 실패·만료면 None.

        generation과 want가 현재 값과 같은지 확인한 뒤 파일과 메모리를 함께 바꾼다.
        검사 중 삭제·재등록·새 다운로드 요청이 들어오면 이전 결과를 적용하지 않는다.
        """
        try:
            with self._lock:
                if (self._closed or (generation is not None and generation != self.generation)
                        or (want is not None and self._want != want)):
                    return None
            try:
                body, temp = self._prepare(template)
            except OSError as e:
                print(f"[호출어 템플릿] 저장 준비 실패 — 이전 템플릿 유지: {e}")
                return None
            with self._lock:
                if (self._closed or (generation is not None and generation != self.generation)
                        or (want is not None and self._want != want)):
                    self._drop_temp(temp)
                    print("[호출어 템플릿] 저장 직전에 상태가 바뀌어 폐기합니다 — 이전 상태 유지")
                    return None
                try:
                    os.replace(temp, self.path)
                except OSError as e:
                    self._drop_temp(temp)
                    print(f"[호출어 템플릿] 저장 실패 — 이전 템플릿 유지: {e}")
                    return None
                self.current, self.load_error = template, None
                self._sent_sha = None       # 로컬을 확정했다 — 이제 서버 참조는 _local_sha 로 가린다.
                self.generation += 1        # 다른 본문을 확정했다면 이전에 보낸 sha 도 더는 가릴 이유가 없다
                self._write_seq += 1        # 확정이 곧 새 서버 쓰기다 — 앞선 예약은 여기서 만료된다
                if self._want in (want, hashlib.sha256(body).hexdigest()):
                    # 방금 쓴 것이 서버가 알린 바로 그것이다. 다른 참조를 기다리는 중이면 그 요청은 남겨 둔다 —
                    # 지우면 확인과 저장 사이에 들어온 최신 요청이 알림 없이 사라진다
                    self._want, self._queued = None, False
                done = (body, self.generation, self._write_seq)
            print(f"[호출어 템플릿] {why} — 호출어 \"{template.wake_text}\", 기준 {template.base_n}개")
            return done
        finally:
            with self._lock:
                # 실패·만료된 저장의 자기 알림 보호도 끝낸다 — 다음 서버 참조로 복구할 수 있어야 한다.
                # 그 사이 다른 본문을 보내기 시작했다면 그 쓰기의 보호는 그대로 둔다.
                if self._sent_sha is not None and self._sent_sha == hashlib.sha256(template.npz_bytes()).hexdigest():
                    self._sent_sha = None

    def _drop_temp(self, temp):
        try:
            temp.unlink(missing_ok=True)
        except OSError as e:
            print(f"[호출어 템플릿] 임시 파일 정리 실패: {e}")

    def clear(self, why):
        """서버가 '등록본 없음' 을 알렸다 — 로컬 파일·메모리·진행 중 작업을 함께 무효화한다.
        파일 삭제도 저장과 같은 잠금 구간에서 한다 — 삭제 직후에 끝난 저장이 파일만 되살리지 못하게."""
        with self._lock:
            if self._closed:
                return False
            had = self.current is not None or self.path.exists()
            self.current, self.load_error = None, None
            self.generation += 1        # 진행 중인 다운로드·등록은 이 시점부터 전부 만료다
            self._write_seq += 1        # 큐에 있던 업로드도 만료다 — 지운 등록본을 다시 올리지 않는다
            self._want, self._queued, self._upload = None, False, None
            try:
                self.path.unlink(missing_ok=True)
            except OSError as e:
                print(f"[호출어 템플릿] 로컬 파일 삭제 실패: {e}")
        if had:
            print(f"[호출어 템플릿] {why} — 로컬 등록본을 지웠습니다. 다시 등록해야 세션이 열립니다")
        return had

    # ── BE 동기화 ──
    def on_blob(self, sha256):
        """BE의 blobs.wakeword 반영. null이면 로컬 등록본도 지운다.

        직접 업로드한 파일의 알림은 해시로 구분해 건너뛴다. 업로드 중 받은 다른 해시는 완료 후 확인한다.
        NOTE(한계): PUT은 If-Match를 지원하지 않아, 다른 클라이언트와 동시에 저장하면 최신 알림으로 다시 맞춘다.
        """
        if sha256 is None:
            return self.clear("서버에 등록본이 없습니다")
        if (not isinstance(sha256, str) or len(sha256) != 64
                or any(c not in "0123456789abcdefABCDEF" for c in sha256)):
            print("[호출어 템플릿] 잘못된 blob 참조 — 기존 템플릿 유지")
            return False
        want = sha256.lower()
        if want == self._local_sha() and self.current is not None:
            return False
        with self._lock:
            if self._closed:
                return False
            if want == self._sent_sha:
                return False        # 우리가 보낸 본문이 돌아온 것이다 — 내려받을 것이 없다
            if self._writers or self._upload is not None:
                # 서버에 쓰는 중이다. 버리지는 않고 참조만 적어 둔다 — 쓰기가 끝난 뒤에도 우리 것과
                # 다르면 그때 내려받는다(_resume_fetch). 지금 받으면 우리가 쓰는 것과 뒤섞인다
                self._want, self._queued = want, False
                print("[호출어 템플릿] 서버에 쓰는 중 — 이 참조는 쓰기가 끝난 뒤에 봅니다")
                return False
            self._want, self._queued = want, True
            if self._worker is None:
                self._worker = threading.Thread(target=self._run_fetch, daemon=True)
                self._worker.start()
            self._lock.notify_all()
        return True

    def _resume_fetch(self):
        """서버 쓰기가 끝났다 — 쓰는 동안 미뤄 둔 참조가 아직 우리 것과 다르면 그때 내려받는다."""
        with self._lock:
            want = self._want
            if (self._closed or want is None or self._queued or self._writers
                    or self._upload is not None or want == self._sent_sha
                    or want == self._local_sha()):
                return
            self._queued = True
            if self._worker is None:
                self._worker = threading.Thread(target=self._run_fetch, daemon=True)
                self._worker.start()
            self._lock.notify_all()

    def _local_sha(self):
        try:
            return hashlib.sha256(self.path.read_bytes()).hexdigest()
        except OSError:
            return None

    def _run_fetch(self):
        """받아야 할 참조가 생길 때마다 깨어난다 — 워커가 끝나는 순간 들어온 요청도 놓치지 않는다.
        받는 사이 더 새 참조가 오면 받던 것을 버리고 그것부터 다시 받는다."""
        from speaker import WakeTemplate

        while True:
            with self._lock:
                self._lock.wait_for(lambda: self._closed or self._queued)
                if self._closed:
                    return
                want, generation = self._want, self.generation
                self._queued = False
            try:
                body = self.link.get_blob_npz("wakeword")
                if hashlib.sha256(body).hexdigest().lower() != want:
                    raise ValueError("내려받은 호출어 템플릿의 sha256 이 수신 참조와 다릅니다")
                template = WakeTemplate.read(io.BytesIO(body))   # 적용 전에 검증한다
            except Exception as e:
                print(f"[호출어 템플릿] 내려받기 실패 — 기존 템플릿 유지: {e}")
                continue
            if self.commit(template, "서버 템플릿 적용", generation=generation, want=want) is None:
                print("[호출어 템플릿] 내려받는 사이 상태가 바뀌어 폐기합니다")
                with self._lock:
                    if generation != self.generation:
                        # 설정 등이 바뀌어 무른 다운로드는 최신 참조로 다시 받는다.
                        # 파일 오류만 난 경우에는 반복하지 않고 다음 서버 알림을 기다린다.
                        self._resume_fetch()

    # ── 서버 쓰기 (등록·연결이 모두 이 길로 나간다) ──
    def reserve_write(self):
        """서버 쓰기 순번을 예약한다 → (순번, 지금 generation). 확정 전 등록본을 먼저 올릴 때 쓴다 —
        예약하는 순간 큐에 있던 이전 등록본 업로드는 만료된다."""
        with self._lock:
            self._write_seq += 1
            return self._write_seq, self.generation

    def write_blob(self, body, seq):
        """서버에 쓴다 → 보냈으면 True, 그 사이 더 새 쓰기가 예약돼 만료면 False. 예외는 호출자가 본다.
        쓸 서버가 없는 로컬 모드도 True 다 — 보낼 곳이 없는 것이지 실패가 아니다.
        모든 서버 쓰기가 이 한 곳을 하나씩 지난다 — 늦게 끝난 이전 본문이 새 본문을 덮지 못한다.
        같은 본문을 다시 보내도 BE 가 sha256 이 같으면 저장·통지를 생략하므로 재시도는 안전하다.
        어떻게 끝나든(보냄·만료·예외) 미뤄 둔 서버 참조를 다시 본다 — 예외로 빠져나가며 보류를 남기면
        그 참조는 다음 알림이 올 때까지 영영 처리되지 않는다."""
        sha = hashlib.sha256(body).hexdigest()
        try:
            with self._put_lock:
                with self._lock:
                    if self._closed or seq != self._write_seq:
                        self.dropped += 1
                        return False
                    if self.link is None or not getattr(self.link, "rt", None):
                        return True
                    # 보내기 전에 적어 둔다 — 이 PUT 이 부른 알림이 PUT 응답보다 먼저 올 수 있다
                    self._sent_sha = sha
                    self._writers += 1
                try:
                    self.put(f"http://127.0.0.1:{self.link.rt['port']}/api/agent/blobs/wakeword",
                             body, "application/octet-stream")
                except Exception:
                    with self._lock:
                        if self._sent_sha == sha:
                            self._sent_sha = None   # 못 보냈다 — 이 sha 로 서버 알림을 가리면 복구가 막힌다
                    raise
                finally:
                    with self._lock:
                        self._writers -= 1
            return True
        finally:
            self._resume_fetch()

    def _queue_upload(self, body, seq):
        """저장할 때 받은 순번으로 업로드를 예약한다. 이전 작업이 최신 대기 작업을 덮지 않도록 먼저 확인한다."""
        if self.link is None or not getattr(self.link, "rt", None):
            return False
        with self._lock:
            if self._closed:
                return False
            if seq != self._write_seq:
                self.dropped += 1
                print("[호출어 템플릿] 업로드 폐기 — 그 사이 더 새 등록·연결이 생겼습니다")
                return False
            self._upload = (seq, body, 0)   # 최신 한 건만 — 최신만 의미가 있다
            if self._uploader is None:
                self._uploader = threading.Thread(target=self._run_upload, daemon=True)
                self._uploader.start()
            self._lock.notify_all()
        return True

    def _run_upload(self):
        while True:
            with self._lock:
                self._lock.wait_for(lambda: self._closed or self._upload is not None)
                if self._closed:
                    return
                seq, body, tries = self._upload
                self._upload = None
                self._writers += 1          # 서버 참조를 따라가지 않는 구간이 여기서부터다
            failed = None
            try:
                if not self.write_blob(body, seq):
                    print("[호출어 템플릿] 업로드 폐기 — 그 사이 더 새 등록·연결이 생겼습니다")
            except Exception as e:
                failed = e
                print(f"[호출어 템플릿] 업로드 실패(로컬에는 저장됨): {e}")
            with self._lock:
                self._writers -= 1
                # 보냈거나, 더 새 작업이 있거나, 만료된 본문이면 다시 보내지 않는다
                retry = (failed is not None and not self._closed and self._upload is None
                         and seq == self._write_seq)
                if retry and tries + 1 >= WAKE_UPLOAD_TRIES:
                    print(f"[호출어 템플릿] 업로드를 {tries + 1}회 실패해 그만둡니다 — 서버 등록본은 이전 상태입니다."
                          " 다음 서버 동기화에서 로컬이 그쪽으로 되돌려질 수 있습니다")
                    retry = False
                if retry:
                    self._upload = (seq, body, tries + 1)
            # 재시도 상태까지 정한 뒤에 본다 — 다시 보낼 것이 남아 있으면 _resume_fetch 가 보류를 유지한다
            self._resume_fetch()
            if retry:
                with self._lock:
                    self._lock.wait(WAKE_UPLOAD_RETRY_S)   # 그 사이 새 작업이 오면 그것부터 (최신만 남는다)

    def close(self):
        with self._lock:
            self._closed = True
            self._queued, self._upload = False, None
            self._lock.notify_all()


class WakeEnroll:
    """온보딩 "이름 불러보기" 의 AI 측 핸들러 — BE wakeword_enroll_start 로 시작 (206).

    호출어·음질·화자 일치를 확인한 샘플 5개로 WakeTemplate을 만든다.
    샘플마다 wakeword_sample을 보내고, 서버와 로컬 저장이 끝나면 wakeword_done을 보낸다.
    검사를 통과하지 못하면 wakeword_rejected로 사유를 알리고 같은 순번을 다시 받는다.
    저장 완료 전에는 기존 템플릿을 유지한다. 고정 시동어 모델은 학습하지 않는다.
    """

    def __init__(self, link, speaker=None, store=None, wake_model=None):
        self.link = link                    # AgentLink (WS 발신·rt) 또는 스텁
        self.speaker = speaker
        self.store = store                  # WakeTemplateStore — 확정된 템플릿을 여기에 맡긴다
        self.wake_model = wake_model        # 고정 시동어 모델 — 실행 때와 같은 것으로 발음을 확인한다
        self.active = False
        self.started_at = 0.0               # VoiceSession 과 같은 뜻 — 겹치면 나중에 시작한 쪽이 발화를 받는다
        self.last_at = 0.0                  # 마지막 진행(시작·샘플) 시각 — 방치 판정용
        self.wake_text = WAKE_DEFAULT_WORD  # 이번 등록이 대상으로 삼은 호출어 (시작할 때 설정에서 읽는다)
        self.epoch = 0                      # 등록 회차 — 늦게 끝난 이전 회차가 확정하지 못하게 한다
        self._samples = []
        self._embs = []
        self._scores = []                   # 샘플별 시동어 점수 — 실측 기록용(판정에는 쓰지 않는다)
        self._fails = 0                     # 연속 실패 횟수 (안내용, 기준을 느슨하게 하지는 않는다)
        self._preload = None
        self._saving = False                # 5개를 다 모았고 저장만 남았다 — 다음 발화는 새 샘플이 아니라 저장 재시도다
        self._saved = None                  # (회차, 서버에 저장한 본문) — 이 짝이 맞을 때만 서버 쓰기를 건너뛴다

    def _tx(self, type_, data):
        print(f"[BE→] {type_} {json.dumps(data, ensure_ascii=False)}")
        self.link._send({"type": type_, "data": data})

    # ── BE 이벤트 진입점 (AgentLink._on_event 가 호출 — WS 수신 스레드) ──
    def on_start(self):
        log_rx("wakeword_enroll_start", {})
        self.active, self._samples, self._embs, self._scores = True, [], [], []
        self.started_at = self.last_at = time.monotonic()
        self._fails = 0
        self._saving, self._saved = False, None
        self.epoch += 1                     # 앞 회차가 뒤늦게 끝나도 확정하지 못한다
        # 이번 등록이 대상으로 삼는 호출어는 지금 설정값이다 — 설정만 바꾸고 옛 템플릿을 재사용하는 길을 막는다.
        self.wake_text = self.store.wake_word() if self.store else WAKE_DEFAULT_WORD
        if self.speaker is not None:
            self._preload = threading.Thread(target=self.speaker._model, daemon=True)
            self._preload.start()
        print(f"[호출어 수집] 시작({self.epoch}회차) — \"{self.wake_text}\" {WAKE_TOTAL}번")

    def expired(self, now=None):
        """방치된 수집인가 — 마지막 진행 뒤 WAKE_ENROLL_IDLE_S 가 지났다.

        호출어 취소 이벤트가 BE·FE 어느 쪽에도 없어서(보이스는 voice_reg_cancel 이 있다)
        온보딩을 중간에 떠나면 active 가 영원히 남는다. 그동안 모든 발화가 등록 샘플로
        먹혀 음성 명령이 통째로 죽으므로, 스스로 접는 안전망을 둔다."""
        if not self.active:
            return False
        return (time.monotonic() if now is None else now) - self.last_at > WAKE_ENROLL_IDLE_S

    def cancel(self):
        """수집 중인 샘플을 지우고 기존 등록본은 유지한다."""
        if not self.active:
            return False
        self.active, self._saving, self._saved = False, False, None
        self.epoch += 1
        self._samples, self._embs, self._scores = [], [], []
        print("[호출어 수집] 중단 — 이전 호출어 설정과 템플릿을 유지합니다")
        return True

    # ── 메인 루프가 VAD 발화마다 호출 (수집 중엔 brain 대신 여기로) ──
    def on_utter(self, audio_i16, t_utter=None):
        if not self.active:
            return                          # t_utter 는 안 쓴다 — 호출어 수집엔 무를 문장이 없다. 호출부를 하나로 두려고 받아만 둔다
        self.last_at = time.monotonic()     # 진행이 있었다 — 방치 시계를 민다
        if self._saving:
            # 유효한 5개는 이미 모였고 저장만 실패한 상태다 — 여섯 번째 샘플로 받지 않고 저장을 다시 시도한다
            print("[호출어 수집] 저장 재시도 — 모은 샘플은 그대로 쓴다")
            self._finish(self.epoch)
            return
        from brain import WAKE_THRESHOLD, speech_s, wake_clip, wake_clip_is_clean, wake_score_of

        epoch = self.epoch
        audio = np.asarray(audio_i16, dtype=np.int16)
        if self.wake_model is None:
            self._reject("호출어 모델이 없어 등록할 수 없어요.", "시동어 모델 없음")
            return
        # 발음 확인은 실행 때와 같은 고정 모델로 한다 — 등록에서 받아 준 발음이 실행에서 안 걸리는 모순을 없앤다.
        score, i_max, lead = wake_score_of(self.wake_model, audio)
        if i_max is None:
            self._reject(f"\"{self.wake_text}\" 로 들리지 않았어요. 또박또박 다시 불러주세요.",
                         f"시동어 점수 {score:.2f} < {WAKE_THRESHOLD}", "MISMATCH")
            return
        clip, _, clip_end, certain = wake_clip(audio, i_max, lead)   # 자르는 규칙도 실행과 같다
        ok, why, code = wake_clip_is_clean(audio, clip, clip_end, certain)
        if not ok:
            self._reject(REJECT_REASONS.get(code, "또렷하게 다시 불러주세요."), why, code)
            return
        if self.speaker is None:
            self._reject("목소리 분석을 쓸 수 없어 등록할 수 없어요.", "화자 모델 없음")
            return
        if self._preload is not None:
            self._preload.join()            # 첫 샘플이면 모델 로드(첫 12 s)를 여기서 기다린다
            self._preload = None
        try:
            emb = self.speaker.embed(clip)
            if not np.isfinite(emb).all():
                raise ValueError("임베딩에 NaN")
        except Exception as e:
            self._reject("목소리 분석에 실패했어요. 잠시 후 다시 불러주세요.", f"임베딩 실패 {e}")
            return
        if self._embs:
            centroid, _ = self.speaker.centroid_of_embs(self._embs)
            sim = float(emb @ centroid)
            if sim < WAKE_MIN_SIM:
                self._reject("앞서 부른 목소리와 다르게 들려요. 같은 분이 다시 불러주세요.",
                             f"앞 샘플들과 유사도 {sim:.2f} < {WAKE_MIN_SIM}", "INCONSISTENT")
                return
        if epoch != self.epoch or not self.active:
            return                          # 판정하는 사이 등록이 다시 시작됐다
        self._samples.append(clip)
        self._embs.append(emb)
        self._scores.append(score)
        self._fails = 0
        n = len(self._samples)
        print(f"[호출어 수집] 샘플 {n}/{WAKE_TOTAL} (말소리 {speech_s(clip):.2f} s, 시동어 점수 {score:.2f})")
        self._tx("wakeword_sample", {"n": n, "total": WAKE_TOTAL})
        if n >= WAKE_TOTAL:
            self._finish(epoch)

    # ── 내부 ──
    def _reject(self, reason, why, code=None):
        """샘플 거절이나 저장 실패를 알린다. 반복 실패해도 검사 기준은 유지한다.

        code 는 REJECT_CODES 의 TOO_SHORT·TOO_LONG·NOISY·INCONSISTENT·MISMATCH 만 보내고, 목소리 분석 실패·호출어 품질 미달
        (클리핑·잘린 경계·뒤이은 말소리)·호출어 모델 없음·저장 실패는 reason 만 보낸다. 저장 실패도 같은 이벤트로 알리며 순번은 5를 넘기지 않는다.
        """
        self._fails += 1
        n = min(len(self._samples) + 1, WAKE_TOTAL)
        print(f"[호출어 수집] {'저장' if self._saving else f'샘플 {n}'} 실패({code or why}) — {why}, "
              f"다시 기다린다 (연속 {self._fails}회)")
        if self._fails >= REJECT_BUDGET + 1 and not self._saving:
            reason += " 계속 안 되면 조용한 곳에서 마이크에 조금 더 가까이 불러주세요."   # 저장 실패는 말하는 법과 무관하다
        data = {"n": n, "total": WAKE_TOTAL, "reason": reason}
        if code in REJECT_CODES:
            data["code"] = code
        self._tx("wakeword_rejected", data)

    def _finish(self, epoch):
        """5개로 템플릿을 만들어 서버·로컬에 저장한 뒤에야 확정한다.

        서버를 먼저 저장해 로컬 저장 실패 시 다운로드로 복구할 수 있게 한다.
        실패하면 같은 5개로 다시 시도하고, 모두 저장된 뒤 wakeword_done을 보낸다.
        """
        from speaker import WakeTemplate

        if epoch != self.epoch or not self.active:
            print("[호출어 수집] 이전 회차의 마무리 — 적용하지 않습니다")
            return
        if self.store is None:
            self._saving = True
            self._reject("등록본을 저장하지 못했어요. 잠시 후 다시 불러주세요.", "템플릿 저장소 없음")
            return
        self._saving = True                 # 여기부터 들어오는 발화는 샘플이 아니라 저장 재시도다
        template = WakeTemplate(self.wake_text, self._scores, np.asarray(self._embs, dtype=np.float32),
                                len(self._embs))
        # 쓰기 순번을 먼저 예약한다 — 큐에서 기다리던 이전 업로드가 이 등록본을 덮지 못하게.
        seq, generation = self.store.reserve_write()
        body = template.npz_bytes()
        if self._saved != (epoch, body):    # 이 회차의 이 본문만 다시 보내지 않는다
            try:
                sent = self.store.write_blob(body, seq)
            except Exception as e:
                if epoch != self.epoch:
                    print("[호출어 수집] 이전 회차의 업로드 실패 — 새 회차에 반영하지 않습니다")
                    return
                self._reject("등록본을 서버에 저장하지 못했어요. 잠시 후 다시 불러주세요.", f"업로드 실패 {e}")
                return
            if epoch != self.epoch:         # 응답을 기다리는 사이 등록이 다시 시작됐다
                print("[호출어 수집] 이전 회차의 업로드 완료 — 새 회차에 반영하지 않습니다")
                return
            if not sent:
                print("[호출어 수집] 더 새 작업이 생겨 이번 확정을 접습니다")
                return
            self._saved = (epoch, body)     # 로컬 저장이 실패해도 서버에는 남아 있다
        if epoch != self.epoch or not self.store.commit(template, "등록 확정", generation=generation):
            self._reject("등록본을 이 PC 에 저장하지 못했어요. 잠시 후 다시 불러주세요.",
                         "로컬 저장 실패 — 서버에는 저장됨")
            return
        self.active = self._saving = False  # 확정 뒤 들어온 발화는 세지 않는다
        print(f"[호출어 수집] 확정 — 호출어 \"{self.wake_text}\", 기준 {template.base_n}개, "
              f"시동어 점수 {[round(s, 2) for s in template.scores]}")
        self._tx("wakeword_done", {})
