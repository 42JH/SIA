# -*- coding: utf-8 -*-
"""화자 등록의 AI 측 핸들러 — BE voice_* WS 이벤트로 구동 (65).

FE 가 낭독 문장을 화면에 띄우고, BE 가 voice_collect{tempId, n} 으로 "n번 문장 수집" 을 지시한다.
AI 는 그 다음 VAD 발화를 n번 샘플로 받아 voice_progress{n} 을 보내고, 마지막 문장 뒤 샘플들의 평균
임베딩(centroid)을 npz 로 만들어 REST 로 올린 뒤 voice_captured 를 보낸다. voice_enroll.py 의 CLI 등록을
이벤트 구동으로 옮긴 것 — 임베딩·centroid 계산은 speaker.SpeakerVerifier 그대로 쓴다.

계약(dev/be 71207bb 프로토콜 §8.7):
- 문장 원문은 BE 가 보내지 않는다. SENTENCES 의 n번째 — FE 상수와 글자 단위로 같아야 한다.
- 같은 n 이 다시 오면 그 문장을 교체 수집("이 문장 다시"). "다시 녹음" 은 BE 가 n=1 부터 다시 발급한다.
  둘 다 n번과 그 뒤 샘플도 함께 버린다.
- 음질 미달이면 voice_quality_warn 을 보내고 멈춘다. FE "그대로 진행" → voice_finalize 가 와야 업로드한다.
- 샘플 wav → npz 순으로 PUT 한 뒤 voice_captured. BE 가 곧장 FE 에 voice_review(재생 URL 포함)를 주기 때문.
- 로컬 프로필(models/speaker.npz)은 여기서 안 건드린다. 확정은 FE voice_commit 이고, 활성이 되면 BE 가
  voice_changed 를 보내므로 그때 활성 npz 를 내려받아 교체한다 — 중단·미확정 등록이 쓰던 프로필을 덮지 않게.

NOTE(한계): 샘플은 VAD 발화 통째(프리롤 2 s 포함) — CLI 등록과 같은 입력이라 화자 연구소 실측과 조건이 같다.
"""
import json
import threading
import urllib.request

import numpy as np

SR = 16000
SENTENCES = [  # FE 와 공통 상수 — 순서·글자를 바꾸면 FE 도 같이 바꿔야 한다
    "시아야 지금 화면 좀 정리해줘",
    "오늘 날씨가 참 맑고 좋다",
    "이 파일을 다른 폴더로 옮겨줄래",
    "다음 영상으로 넘어가고 음소거 해줘",
    "안녕하세요 저는 이 컴퓨터의 주인입니다",
]
MIN_SPEECH_S = 1.5     # NOTE(튜닝): 말소리가 이보다 짧으면 문장 낭독이 아니다(헛기침·"어") — 같은 문장을 기다린다. voice_enroll 과 같은 값
QUALITY_MIN_SIM = 0.5  # NOTE(튜닝): 샘플 간 최소 코사인 유사도 하한. voice_enroll 의 "양호" 기준. 미만이면 FE 에 음질 경고
NOISE_RMS = 350.0      # NOTE(튜닝): 조용한 블록(하위 20%)의 rms 가 이보다 크면 소음 "높음" — VAD 시작 임계 하한과 같은 값


def noise_level(audio_i16, block=480):
    """주변 소음 표기(낮음/높음) — 말소리 블록은 빼고 조용한 블록(하위 20%)의 rms 바닥만 본다. 한 블록 미만이면 None."""
    n = len(audio_i16) // block
    if n == 0:
        return None
    rms = np.sqrt(np.mean(np.asarray(audio_i16[:n * block], dtype=np.float32).reshape(n, block) ** 2, axis=1))
    return "높음" if np.percentile(rms, 20) > NOISE_RMS else "낮음"


def log_rx(type_, data):
    """BE 가 보낸 화자 등록 이벤트를 한 줄로 남긴다 — 실기동 때 무엇이 언제 왔는지 눈으로 확인하려고.
    조건이 안 맞아 무시되는 이벤트도 찍힌다. 그래야 "안 왔다" 와 "왔는데 무시했다" 를 구분할 수 있다."""
    print(f"[BE←] {type_} {json.dumps(data, ensure_ascii=False)}")


class VoiceSession:
    def __init__(self, link, speaker, profile_path):
        self.link = link                    # AgentLink (WS 발신·rt) 또는 스텁
        self.speaker = speaker              # SpeakerVerifier — 임베딩·centroid 계산, 활성 교체 시 reload
        self.profile_path = str(profile_path)
        self.active = False
        self.tempId = None
        self.total = len(SENTENCES)
        self._n = 0                         # 수집 중인 문장(0=대기)
        self._samples = {}                  # n -> int16 오디오
        self._result = None                 # (npz, wav, durationSec, quality, noise) — 경고 뒤 voice_finalize 대기용
        self._preload = None                # 모델 프리로드 스레드

    def _tx(self, type_, data):
        """BE 로 나가는 화자 등록 이벤트는 전부 여기를 지난다 — 보낸 것도 한 줄씩 남긴다."""
        print(f"[BE→] {type_} {json.dumps(data, ensure_ascii=False)}")
        self.link._send({"type": type_, "data": data})

    # ── BE 이벤트 진입점 (AgentLink._on_event 가 호출 — WS 수신 스레드) ──
    def on_start(self, tempId, total=None):
        log_rx("voice_reg_start", {"tempId": tempId, "total": total})
        self.tempId, self.active = tempId, True
        self.total = int(total or len(SENTENCES))
        self._samples, self._n, self._result = {}, 0, None
        # 모델(첫 로드 12 s)은 낭독하는 동안 미리 — 마무리 때 메인 루프가 멈추지 않게. 이미 로드됐으면 즉시 끝난다
        self._preload = threading.Thread(target=self.speaker._model, daemon=True)
        self._preload.start()
        self._tx("voice_ready", {"tempId": tempId})

    def on_collect(self, tempId, n):
        log_rx("voice_collect", {"tempId": tempId, "n": n})
        if not self.active or tempId != self.tempId or not n:
            return
        self._n = int(n)
        # n번을 다시 읽으라는 뜻이니 n번과 그 뒤에 받아 둔 샘플은 버린다 — 안 버리면 "다시 녹음"(n=1) 때
        # 앞서 읽은 2·3번이 남아, 새 1번 발화 하나만으로 "문장이 다 모였다" 가 되어 등록이 일찍 끝난다
        keep = {k: v for k, v in self._samples.items() if k < self._n}
        dropped = len(self._samples) - len(keep)
        self._samples = keep
        self._result = None                 # "다시 녹음" 이면 이전 결과는 폐기
        text = SENTENCES[self._n - 1] if self._n <= len(SENTENCES) else "?"
        if dropped:
            print(f"[화자 등록] 문장 {self._n}/{self.total} 재수집 — 이전 샘플 {dropped}개 폐기")
        print(f"[화자 등록] 문장 {self._n}/{self.total}: \"{text}\"")

    def on_finalize(self, tempId):
        """FE 가 음질 경고를 "그대로 진행" 으로 넘김 → 경고 때 만들어 둔 결과를 그대로 올린다."""
        log_rx("voice_finalize", {"tempId": tempId})
        if self.active and tempId == self.tempId and self._result:
            self._upload_and_capture()

    def on_cancel(self, tempId):
        log_rx("voice_reg_cancel", {"tempId": tempId})
        self.active, self._n, self._samples, self._result = False, 0, {}, None
        print("[화자 등록] 중단 — 이전 프로필 유지")

    def on_registered(self, prof_id, is_active):
        log_rx("voice_registered", {"id": prof_id, "active": is_active})
        # 프로필 확정. 활성 여부는 BE 가 정한다 — 활성 리로드는 voice_changed 에서만
        self.active = False
        print(f"[화자 등록] 프로필 확정 id={prof_id} active={is_active}")

    def on_changed(self, data):
        """활성 보이스가 바뀜 → 활성 npz 를 내려받아 로컬 프로필 교체 + 게이트 즉시 갱신(재시작 불필요)."""
        log_rx("voice_changed", data)
        try:
            url = f"http://127.0.0.1:{self.link.rt['port']}/api/agent/voices/active/npz"
            with urllib.request.urlopen(url, timeout=15) as r:
                body = r.read()
            print(f"[BE REST] GET {url} → {r.status} ({len(body)} B)")
            with open(self.profile_path, "wb") as f:
                f.write(body)
            self.speaker.reload()
            print(f"[화자 등록] 활성 보이스 리로드 id={data.get('id')} → {self.profile_path}")
        except Exception as e:
            print(f"[화자 등록] 활성 npz 리로드 실패: {e}")

    # ── 메인 루프가 VAD 발화마다 호출 (등록 중엔 brain 대신 여기로) ──
    def on_utter(self, audio_i16):
        if not self.active or self._n == 0:
            return
        from brain import speech_s

        spoken = speech_s(audio_i16)
        if spoken < MIN_SPEECH_S:
            print(f"[화자 등록] 너무 짧음({spoken:.1f} s) — 문장 {self._n} 을 다시 기다린다")
            return
        n, self._n = self._n, 0
        self._samples[n] = np.asarray(audio_i16, dtype=np.int16)
        self._tx("voice_progress", {"tempId": self.tempId, "n": n})
        if all(k in self._samples for k in range(1, self.total + 1)):
            self._finish()

    # ── 내부 ──
    def _finish(self):
        from brain import wav_bytes

        if self._preload is not None:
            self._preload.join()
        audios = [self._samples[k] for k in range(1, self.total + 1)]
        centroid, min_sim = self.speaker.centroid_of(audios)
        wav = np.concatenate(audios)
        noise = noise_level(wav)
        quality = "양호" if min_sim >= QUALITY_MIN_SIM else "낮음"
        self._result = (self.speaker.npz_bytes(centroid), wav_bytes(wav), round(len(wav) / SR, 1), quality, noise)
        print(f"[화자 등록] 샘플 일관성 {min_sim:.2f} → {quality}, 소음 {noise}")
        if quality != "양호":
            self._tx("voice_quality_warn", {
                "tempId": self.tempId, "reason": f"목소리가 일정하지 않아요 (샘플 유사도 {min_sim:.2f})", "noise": noise})
            return                          # FE 가 "그대로 진행" 하면 voice_finalize 가 온다
        self._upload_and_capture()

    def _upload_and_capture(self):
        npz, wav, dur, quality, noise = self._result
        base = f"http://127.0.0.1:{self.link.rt['port']}/api/agent/voices/{self.tempId}"
        try:
            self._put(base + "/sample", wav, "audio/wav")
            self._put(base + "/npz", npz, "application/octet-stream")
        except Exception as e:
            print(f"[화자 등록] 업로드 실패: {e}")  # voice_captured 는 보낸다 — FE 가 멈추지 않게. 확정(commit)은 BE 가 npz 없음으로 거절한다
        self._tx("voice_captured", {
            "tempId": self.tempId, "durationSec": dur, "quality": quality, "noise": noise})
        self._result = None

    @staticmethod
    def _put(url, body, ctype):
        req = urllib.request.Request(url, data=body, method="PUT")
        req.add_header("Content-Type", ctype)
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"[BE REST] PUT {url} {ctype} ({len(body)} B) → {r.status}")
