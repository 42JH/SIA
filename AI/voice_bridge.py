# -*- coding: utf-8 -*-
"""화자 등록의 AI 측 핸들러 — BE voice_* WS 이벤트로 구동 (65).

FE 가 낭독 문장을 화면에 띄우고, BE 가 voice_collect{tempId, n} 으로 "n번 문장 수집" 을 지시한다.
AI 는 그 다음 VAD 발화를 n번 샘플로 받아 그 자리에서 임베딩을 뽑고 voice_progress{n} 을 보낸다. 마지막 문장 뒤에는
모아 둔 임베딩의 평균(centroid)을 npz 로 만들어 REST 로 올린 뒤 voice_captured 를 보낸다. voice_enroll.py 의 CLI 등록을
이벤트 구동으로 옮긴 것 — 임베딩·centroid 계산은 speaker.SpeakerVerifier 그대로 쓴다.

계약(dev/be 4ce6ec3 프로토콜 §8.7):
- 문장 원문은 BE 가 보내지 않는다. SENTENCES 의 n번째 — FE 상수와 글자 단위로 같아야 한다.
- 같은 n 이 다시 오면 그 문장을 교체 수집("이 문장 다시"). "다시 녹음" 은 BE 가 n=1 부터 다시 발급한다.
  둘 다 n번과 그 뒤 샘플도 함께 버린다. 그 지시보다 먼저 시작된 발화도 버린다 — 무르려던 낭독이 VAD 에서 뒤늦게
  나와 그대로 통과하는 사고를 막는다.
- 문장 하나가 미달이면 voice_sentence_rejected{tempId, n, reason, code} 를 보내고 같은 문장을 계속 기다린다 — 순번을
  진행하지 않는다. code 는 TOO_SHORT · TOO_LONG · NOISY · INCONSISTENT, FE 는 모르는 code 면 reason 을 쓴다.
  소음·불일치 거절은 등록 1회당 각각 REJECT_BUDGET 번까지 — 선풍기 소음이나 찌그러진 1번 문장에 영영 갇히지 않게.
  비슷한 이름은 다른 뜻이다 — voice_rejected 는 실행 중 화자 게이트 거부(4.1), voice_reg_denied 는 프로필 4개 초과.
- 1번 문장이 찌그러진 채 기준이 된 경우: 같은 문장을 두 번 읽었는데 둘은 닮았고 앞 문장 하나와만 다르면 앞 문장을 의심해
  기준에서 빼고 이번 문장을 받는다(2 대 1). 마지막엔 혼자 튀는 문장 하나를 프로필 평균에서 뺀다. BE 는 순번을 되돌릴 수
  없어 앞 문장을 다시 읽히진 못한다 — 프로필에서만 걸러낸다.
- 통과한 문장은 voice_progress{tempId, n, durationSec, quality, noise} 로 판독 결과를 같이 보낸다. FE 가 문장마다
  "판독 결과 · 녹음 품질" 을 띄우고 거기서 "다시 녹음" 을 받기 때문 — 5문장 뒤에 한 번 주면 그 화면이 매번 "미판정" 이다.
  quality 는 앞 문장들과 유사도가 QUALITY_MIN_SIM 미만이거나 소음이 높으면 "낮음", 1번 문장은 비교 대상이 없어 소음만 본다.
  NOTE(한계): BE 가 onProgress 에서 이 세 필드를 FE 로 넘겨야 화면에 뜬다 (2026-09-10 실측 19/21, 미통과 2건 중 하나).
- 5문장을 다 모으면 voice_quality_warn 없이 바로 올린다 — 문장마다 결과를 줬으니 그 자리에서 다시 읽는 쪽이 빠르다.
- 샘플 wav → npz 순으로 PUT 한 뒤 voice_captured(5문장 전체 판정). BE 가 곧장 FE 에 voice_review(재생 URL 포함)를 주고
  FE 는 그걸 받아야 "등록" 버튼을 열기 때문.
- 로컬 프로필(models/speaker.npz)은 여기서 안 건드린다. 확정은 FE voice_commit 이고, 활성이 되면 BE 가
  voice_changed 를 보내므로 그때 활성 npz 를 내려받아 교체한다 — 중단·미확정 등록이 쓰던 프로필을 덮지 않게.

NOTE(한계): 샘플은 VAD 가 잘라 준 발화를 자르지 않고 통째로 쓴다(말 시작 전 여유분 2 s 포함) — CLI 등록(voice_enroll.py)과
같은 입력이라 화자 인증을 실측했을 때와 조건이 같다.

온보딩은 2단계다 — ① "시아야" 5회(WakeEnroll, wakeword_*) → ② "명령하듯 말해보세요" 5문장 낭독 = 이 화자 등록
(VoiceSession, voice_*). ②에서 문장마다 임베딩하고 프로필을 만든다. 같은 5문장을 한 번 더 읽히던 command_* 단계는
아무것도 만들지 않는 중복이라 폐기됐다(229) — BE 는 그 이벤트를 받아도 무시한다.
"""
import io
import json
import threading
import time
import urllib.request

import numpy as np

SR = 16000
SENTENCES = [  # 화자 인증 등록 문장 5개 — FE 와 공통 상수. 순서·글자를 바꾸면 FE 도 같이 바꿔야 한다
    "시아야 지금 화면 좀 정리해줘",
    "오늘 날씨가 참 맑고 좋다",
    "이 파일을 다른 폴더로 옮겨줄래",
    "다음 영상으로 넘어가고 음소거 해줘",
    "안녕하세요 저는 이 컴퓨터의 주인입니다",
]
MIN_SPEECH_S = 0.4     # NOTE(튜닝): 짧은 발화 거르기 전용 — 헛기침·"어"·클릭음(말소리 ≤ 0.3 s, WAKE_MIN_S 와 같은 근거)만 TOO_SHORT 로
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
NOISE_RMS = 350.0      # NOTE(튜닝): 조용한 블록(하위 20%)의 rms 가 이보다 크면 소음 "높음" — VAD 시작 임계 하한과 같은 값
WAKE_TOTAL = 5         # 온보딩 "시아야" 부르기 샘플 수 — FE 진행바의 total 과 같은 값. 10 이었다가 5 로 줄임 (2026-09-10)
WAKE_MIN_S = 0.3       # NOTE(튜닝): "시아야" 말소리 하한. 이보다 짧으면 헛기침·클릭음으로 보고 세지 않는다
WAKE_MAX_S = 2.0       # NOTE(튜닝): 말소리 상한. 이보다 길면 문장을 말한 것이라 이름 부르기로 세지 않는다


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
        self._embs = {}                     # n -> 임베딩. 문장을 받을 때 그 자리에서 채운다
        self._rejects = 0                   # 이번 등록에서 목소리 불일치로 무른 횟수 (REJECT_BUDGET 까지)
        self._noisy = 0                     # 이번 등록에서 소음으로 무른 횟수 (REJECT_BUDGET 까지)
        self._last_reject = None            # (n, 임베딩) — 직전에 목소리 불일치로 무른 시도. 같은 문장 두 시도를 견주는 데 쓴다
        self._suspect = set()               # 찌그러진 것으로 의심돼 비교 기준에서 뺀 문장 번호
        self._collect_t = 0.0               # 마지막 voice_collect 시각 — 그보다 먼저 시작된 발화는 이전 지시의 것이다
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
        self._samples, self._embs, self._n, self._rejects, self._noisy = {}, {}, 0, 0, 0
        self._last_reject, self._suspect = None, set()
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

    def on_cancel(self, tempId):
        log_rx("voice_reg_cancel", {"tempId": tempId})
        self.active, self._n, self._samples, self._embs, self._rejects = False, 0, {}, {}, 0
        self._last_reject, self._suspect = None, set()
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
    def on_utter(self, audio_i16, t_utter=None):
        if not self.active or self._n == 0:
            return
        if t_utter is not None and t_utter < self._collect_t:
            # "이 문장 다시" 를 누르기 직전에 시작한 낭독 — 받으면 방금 무르려던 그 발화로 문장이 넘어간다.
            # VAD 는 말이 끝나고 0.55 s 뒤에야 발화를 넘겨주므로 이 순서가 실제로 생긴다
            print(f"[화자 등록] 문장 {self._n} 지시보다 먼저 시작된 발화 — 버리고 다시 기다린다")
            return
        from brain import speech_s

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
        self._n = 0
        self._samples[n], self._embs[n] = audio, emb
        # 이 문장의 판독 결과 — 거절 예산이 떨어져 받아 준 문장도 여기서 "낮음" 이 되어 사용자가 그 자리에서 다시 읽을 수 있다
        quality = "양호" if (sim is None or sim >= QUALITY_MIN_SIM) and noise != "높음" else "낮음"
        # 통과 로그 — 실측 때 VOICE_MIN_SIM·MIN_SPEECH_S 를 맞추는 근거. 예산 소진 뒤 통과한 문장도 유사도가 남는다
        print(f"[화자 등록] 문장 {n} 통과 — 말소리 {spoken:.1f} s, "
              + (f"앞 문장들과 유사도 {sim:.2f}" if sim is not None else "첫 문장(비교 없음)")
              + f", 품질 {quality}, 소음 {noise}")
        self._tx("voice_progress", {"tempId": self.tempId, "n": n, "durationSec": round(len(audio) / SR, 1),
                                    "quality": quality, "noise": noise})
        if all(k in self._samples for k in range(1, self.total + 1)):
            self._finish()

    # ── 내부 ──
    def _reject(self, n, code, reason, why):
        """문장 하나를 무르고 사유를 보낸다. self._n 은 그대로 둔다 — 순번을 진행하지 않고 같은 문장을 계속 기다린다."""
        print(f"[화자 등록] 문장 {n} 거절({code or '사유만'}) — {why}, 다시 기다린다")
        data = {"tempId": self.tempId, "n": n, "reason": reason}
        if code:
            data["code"] = code             # 없으면 키 자체를 넣지 않는다 — BE 계약 (FE 는 reason 으로 폴백)
        self._tx("voice_sentence_rejected", data)

    def _finish(self):
        from brain import wav_bytes

        keys = list(range(1, self.total + 1))
        # 혼자 튀는 문장 하나는 프로필 평균에서 뺀다 — 찌그러진 1번이 기준이 됐던 경우가 여기서 걸러진다.
        # 각 문장을 나머지 평균과 견줘, 하나만 VOICE_MIN_SIM 아래이고 나머지는 전부 QUALITY_MIN_SIM 이상일 때만 뺀다.
        # 둘 이상 튀면 어느 쪽이 본인인지 모르니 그대로 두고 voice_captured 의 quality 를 "낮음" 으로 보낸다
        loo = {k: float(self._embs[k] @ self.speaker.centroid_of_embs([self._embs[j] for j in keys if j != k])[0]) for k in keys}
        low = [k for k in keys if loo[k] < VOICE_MIN_SIM]
        use = keys
        if len(low) == 1 and all(loo[k] >= QUALITY_MIN_SIM for k in keys if k != low[0]):
            use = [k for k in keys if k != low[0]]
            print(f"[화자 등록] 문장 {low[0]} 이 나머지와 안 닮음(유사도 {loo[low[0]]:.2f}) — 프로필 평균에서 빼고 {len(use)}문장으로 만든다")
        centroid, min_sim = self.speaker.centroid_of_embs([self._embs[k] for k in use])
        wav = np.concatenate([self._samples[k] for k in keys])   # 재생용 샘플은 다섯 문장 다 — 사용자가 들은 그대로
        noise = noise_level(wav)
        quality = "양호" if min_sim >= QUALITY_MIN_SIM else "낮음"
        print(f"[화자 등록] 샘플 일관성 {min_sim:.2f} → {quality}, 소음 {noise}")
        self._upload_and_capture(self.speaker.npz_bytes(centroid), wav_bytes(wav), round(len(wav) / SR, 1), quality, noise)

    def _upload_and_capture(self, npz, wav, dur, quality, noise):
        base = f"http://127.0.0.1:{self.link.rt['port']}/api/agent/voices/{self.tempId}"
        try:
            self._put(base + "/sample", wav, "audio/wav")
            self._put(base + "/npz", npz, "application/octet-stream")
        except Exception as e:
            print(f"[화자 등록] 업로드 실패: {e}")  # voice_captured 는 보낸다 — FE 가 멈추지 않게. 확정(commit)은 BE 가 npz 없음으로 거절한다
        self._tx("voice_captured", {
            "tempId": self.tempId, "durationSec": dur, "quality": quality, "noise": noise})

    @staticmethod
    def _put(url, body, ctype):
        req = urllib.request.Request(url, data=body, method="PUT")
        req.add_header("Content-Type", ctype)
        with urllib.request.urlopen(req, timeout=15) as r:
            print(f"[BE REST] PUT {url} {ctype} ({len(body)} B) → {r.status}")


class WakeEnroll:
    """온보딩 "이름 불러보기" 의 AI 측 핸들러 — BE wakeword_enroll_start 로 시작 (206).

    FE 가 "시아야" 를 WAKE_TOTAL(5)번 부르게 하고, 부를 때마다 AI 가 wakeword_sample{n, total} 을 보내 진행바를 채운다.
    다 모이면 샘플 원본을 npz 하나로 묶어 PUT /api/agent/blobs/wakeword 로 올리고 wakeword_done 을 보낸다.
    FE 는 wakeword_done 이 와야 "다음" 버튼을 연다. 호출어 모델(고정 파일)은 여기서 바꾸지 않고 BE 도 npz 를 저장만 한다.
    NOTE(한계): 샘플 판정은 말소리 길이뿐 — 실제로 "시아야" 라고 했는지는 확인하지 않는다.
    """

    def __init__(self, link):
        self.link = link                    # AgentLink (WS 발신·rt) 또는 스텁
        self.active = False
        self._samples = []
        self._put = VoiceSession._put       # REST 업로드 — 테스트에서 바꿔 끼운다

    def _tx(self, type_, data):
        print(f"[BE→] {type_} {json.dumps(data, ensure_ascii=False)}")
        self.link._send({"type": type_, "data": data})

    # ── BE 이벤트 진입점 (AgentLink._on_event 가 호출 — WS 수신 스레드) ──
    def on_start(self):
        log_rx("wakeword_enroll_start", {})
        self.active, self._samples = True, []
        print(f"[호출어 수집] 시작 — \"시아야\" {WAKE_TOTAL}번")

    # ── 메인 루프가 VAD 발화마다 호출 (수집 중엔 brain 대신 여기로) ──
    def on_utter(self, audio_i16, t_utter=None):
        if not self.active:
            return                          # t_utter 는 안 쓴다 — 호출어 수집엔 무를 문장이 없다. 호출부를 하나로 두려고 받아만 둔다
        from brain import speech_s

        spoken = speech_s(audio_i16)
        if not WAKE_MIN_S <= spoken <= WAKE_MAX_S:
            print(f"[호출어 수집] 말소리 {spoken:.1f} s — 이름 부르기로 안 봄, 다시 기다린다")
            return
        self._samples.append(np.asarray(audio_i16, dtype=np.int16))
        n = len(self._samples)
        print(f"[호출어 수집] 샘플 {n}/{WAKE_TOTAL} ({spoken:.1f} s)")
        self._tx("wakeword_sample", {"n": n, "total": WAKE_TOTAL})
        if n >= WAKE_TOTAL:
            self._finish()

    # ── 내부 ──
    def _finish(self):
        self.active = False                 # 업로드 중 들어온 발화는 세지 않는다
        buf = io.BytesIO()
        np.savez(buf, sr=SR, **{f"sample{i:02d}": a for i, a in enumerate(self._samples, 1)})
        try:
            self._put(f"http://127.0.0.1:{self.link.rt['port']}/api/agent/blobs/wakeword",
                      buf.getvalue(), "application/octet-stream")
        except Exception as e:
            print(f"[호출어 수집] 업로드 실패: {e}")  # wakeword_done 은 보낸다 — FE 가 멈추지 않게. BE 는 저장만 하는 데이터다
        self._tx("wakeword_done", {})
