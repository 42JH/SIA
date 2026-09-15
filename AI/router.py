# -*- coding: utf-8 -*-
"""1단 로컬 라우터 — 자주 쓰는 고정 명령을 LLM 없이 즉시 액션으로.

로컬 STT(faster-whisper) → 단어 사전 매칭. 사전에 걸리면 LLM 판정과 동일한
스키마의 액션 dict를 반환하고(brain._execute가 그대로 실행), 안 걸리면
None → 호출측이 LLM(2단)으로 승격하며 STT 초안을 힌트로 첨부한다.

승격이 기본인 것들: 지시어("이거") — 화면·시선이 필요, 질문·요약 — answer
생성 필요, 확인 대기 중 발화 — 승인/거부 판정 필요(호출측에서 차단).
1단 v1 범위는 안전한 명령만: 앱 실행, 미디어 제어, 세션 종료. 창 닫기·삭제
같은 파괴적 동작은 확인 흐름이 필요해서 LLM 경로에 남긴다.

모델: 환경변수 STT_MODEL (기본 base, CPU int8). 첫 발화 때 lazy load.
실측(2초 오디오, CPU int8): base 0.84~0.94s / small 1.7~2.6s — 1단 목표
(1초 미만)는 base만 충족. 오인식 비용은 LLM 승격뿐이라 빠른 쪽이 기본.
NOTE(한계): 매칭은 공백 제거 후 부분 문자열 — 활용형이 사전을 벗어나면
승격된다. 회귀 케이스로 1단 적중률을 실측한 뒤 형태소 분석기(kiwipiepy)
도입을 판단한다.
"""
import os
import re
import time



def _cuda_available():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


# STT 설정 — 기본 "auto": GPU(ctranslate2 CUDA)가 있으면 small·float16·beam5·어휘 프롬프트, 없으면 base·int8·beam1.
# 실측(eval --tier1 59케이스, 2026-09-15): base·cpu 5적중/22미스/중앙 0.72s → small·cuda+프롬프트 20적중/7미스/0.13s, 오답 0.
# CPU 에선 프롬프트를 끈다 — base 가 프롬프트 어휘로 환각('일시정지.' 오답 2건)해 즉시 실행이 틀리기 때문.
STT_DEVICE = os.environ.get("STT_DEVICE", "auto")
if STT_DEVICE == "auto":
    STT_DEVICE = "cuda" if _cuda_available() else "cpu"
_GPU = STT_DEVICE.startswith("cuda")
MODEL_NAME = os.environ.get("STT_MODEL") or ("small" if _GPU else "base")
STT_COMPUTE = os.environ.get("STT_COMPUTE") or ("float16" if _GPU else "int8")
STT_BEAM = int(os.environ.get("STT_BEAM") or (5 if _GPU else 1))
# 환각 가드 — 세그먼트 최저 avg_logprob 가 이 값 미만이면 1단 즉시 실행을 포기하고 LLM 으로 승격한다.
# 실측(small·cuda·프롬프트, 59케이스): 정답 적중 22건 logprob -0.79~-0.16, 유일한 오답(사인오프를 '다음곡.'으로 환각) -1.09.
STT_MIN_LOGPROB = float(os.environ.get("STT_MIN_LOGPROB") or -0.9)

# 화면·시선이 필요한 지시어 — 1단이 절대 처리하면 안 됨
DEICTIC = ("이거", "저거", "그거", "여기", "저기", "이 창", "이 파일", "이걸", "그걸")
# answer 생성이 필요한 발화 표지 — LLM 몫
ASK = ("뭐야", "뭐지", "뭔데", "설명", "요약", "번역", "알려줘", "어때")

APPS_KO = {"계산기": "calc", "메모장": "notepad", "크롬": "chrome",
           "탐색기": "explorer", "그림판": "paint"}
OPEN_VERBS = ("열어", "켜", "띄워", "실행", "틀어")

MEDIA_KO = [  # (키워드들, media_key, say)
    (("음소거", "소리꺼", "소리켜"), "mute", "음소거를 전환할게요"),
    (("다음곡", "다음 곡", "다음영상", "다음 영상", "다음노래"), "next", "다음으로 넘길게요"),
    (("이전곡", "이전 곡", "이전영상", "이전 영상", "이전노래"), "prev", "이전으로 돌릴게요"),
    # playpause 는 마지막 — "다음곡 틀어줘"의 "틀어"가 next 보다 먼저 잡히면 안 된다(실측 오답)
    (("일시정지", "일시 정지", "멈춰", "재생", "시작해", "틀어"), "playpause", "재생을 전환할게요"),
]
# 볼륨은 명사+동사 쌍 — "볼륨 좀 올려줘"·"볼륨을 80까지 올려줘"처럼 사이에 조사·군말이 끼어도 잡는다(실측 미스 2건).
VOL_NOUNS = ("볼륨", "소리")
VOL_UP = ("올려", "키워", "높여", "업")
VOL_DOWN = ("내려", "줄여", "낮춰", "다운")

# initial_prompt 어휘 힌트 — 사전과 같은 표에서 만들어 항상 동기화. 짧은 한국어 명령의 오인식을 크게 줄인다(위 실측).
DEFAULT_PROMPT = ("시아야. " + " ".join(f"{a} 열어줘." for a in APPS_KO) + " "
                  + " ".join(f"{ws[0]}." for ws, _, _ in MEDIA_KO)
                  + " 볼륨 올려줘. 볼륨 내려줘. 이거 저장해줘. 창 최대화. 다음 탭. 종료.")
STT_PROMPT = (os.environ["STT_PROMPT"] or None) if "STT_PROMPT" in os.environ else (DEFAULT_PROMPT if _GPU else None)

# NOTE(튜닝): 흔한 동사("들어가" 등)는 오탐 실측 후 제거됨 — '유튜브 들어가줄래'가
# end_session 으로 처리된 사례(2026-09-03). 부분 일치는 명시적 종료 표현만.
END_EXACT = ("그만", "끝", "종료")            # 발화 전체가 이것일 때만
END_KO = ("이제그만", "그만해", "이제됐어",    # 부분 일치 허용
          "수고하셨", "수고했", "안녕히", "다음에만나", "다음영상에서만나", "그럼안녕")  # 종료 인사(실측 라벨 end_session)

# 호출어의 STT 흔한 오표기 — 동음·유사 발음만 (실측 기반으로 추가)
# NOTE(튜닝): 미인식↑면 변형을 추가하고, 엉뚱한 발화가 통과하면 뺀다.
# 짧은 변형("시아"·"시야")은 시아버지·시야 같은 일상 단어에 오탐하므로 넣지 않는다
WAKE_VARIANTS = {"시아야": ("시아야", "시야야", "씨아야")}


def _compact(text):
    return re.sub(r"[^\w]", "", text)


class Router:
    def __init__(self, wake_word):
        self.wakes = tuple(_compact(w) for w in
                           WAKE_VARIANTS.get(wake_word, (wake_word,)))
        self._model = None
        self.last_logprob = None  # 직전 transcribe 의 세그먼트 최저 avg_logprob (환각 가드·로그용)

    def transcribe(self, audio_i16):
        """발화 오디오 → (텍스트, 소요 초). 모델은 첫 호출 때 로드."""
        import numpy as np
        from faster_whisper import WhisperModel

        if self._model is None:
            t0 = time.monotonic()
            if STT_DEVICE.startswith("cuda"):
                import torch  # noqa: F401 — torch 가 cublas64_12/cudnn64_9 DLL 경로를 등록해 ctranslate2 가 GPU 를 잡는다(별도 CUDA 설치 불필요)
            self._model = WhisperModel(MODEL_NAME, device=STT_DEVICE, compute_type=STT_COMPUTE)
            print(f"STT 모델 로드 ({MODEL_NAME}, {STT_DEVICE}/{STT_COMPUTE}, beam {STT_BEAM}, {time.monotonic() - t0:.1f}s)")
        t0 = time.monotonic()
        a = np.asarray(audio_i16, dtype=np.float32) / 32768.0
        segments, _ = self._model.transcribe(a, language="ko", beam_size=STT_BEAM,
                                             condition_on_previous_text=False, initial_prompt=STT_PROMPT)
        segments = list(segments)
        text = "".join(s.text for s in segments).strip()
        self.last_logprob = min((s.avg_logprob for s in segments), default=None)
        return text, time.monotonic() - t0

    def route(self, text, session_active):
        """텍스트 → 액션 dict 또는 None(승격). 게이트: 호출어 또는 활성 세션."""
        if not text:
            return None
        if self.last_logprob is not None and self.last_logprob < STT_MIN_LOGPROB:
            return None  # 전사 신뢰도 낮음(환각 의심) — 즉시 실행 대신 LLM 승격
        c = _compact(text)
        if any(_compact(d) in c for d in DEICTIC) or any(a in c for a in ASK):
            return None  # 화면·생성이 필요 — LLM 몫
        wake = any(w in c for w in self.wakes)
        if not (wake or session_active):
            return None  # 호출어도 세션도 없음 — 기각 판단은 LLM이 (오인식 방어)

        base = {"audio_is_speech": True, "wake_heard": wake, "is_command": True,
                "transcript": text, "tier": 1}
        for name, key in APPS_KO.items():
            if name in c and any(v in c for v in OPEN_VERBS):
                return {**base, "action": "open_app", "app": key,
                        "say": f"{name}를 열게요"}
        # 종료 인사는 미디어보다 먼저 — "다음 영상에서 만나요"가 '다음 영상'(next)으로 잡히지 않게
        if session_active and (c in END_EXACT or any(e in c for e in END_KO)):
            return {**base, "action": "end_session", "say": "대기 모드로 전환합니다"}
        for words, key, say in MEDIA_KO:
            if any(_compact(w) in c for w in words):
                return {**base, "action": "media", "media_key": key, "say": say}
        if any(n in c for n in VOL_NOUNS):
            if any(v in c for v in VOL_UP):
                return {**base, "action": "media", "media_key": "volup", "say": "볼륨을 올릴게요"}
            if any(v in c for v in VOL_DOWN):
                return {**base, "action": "media", "media_key": "voldown", "say": "볼륨을 내릴게요"}
        return None


def selftest():
    r = Router("시아야")
    hit = r.route("시아야 계산기 열어줘", False)
    assert hit and hit["action"] == "open_app" and hit["app"] == "calc" and hit["wake_heard"]
    hit = r.route("음소거 해줘", True)  # 세션 중엔 호출어 없이도
    assert hit and hit["action"] == "media" and hit["media_key"] == "mute"
    assert r.route("계산기 열어줘", False) is None       # 호출어도 세션도 없음 → 승격
    assert r.route("시아야 이거 저장해줘", False) is None  # 지시어 → 승격
    assert r.route("시아야 이 문서 요약해줘", False) is None  # 생성 필요 → 승격
    assert r.route("시아야 아까 그 파일 다시 띄워봐", False) is None  # 사전 밖 → 승격
    hit = r.route("이제 그만", True)
    assert hit and hit["action"] == "end_session"
    assert r.route("그만", False) is None  # 세션 없는 '그만'은 승격
    # 2026-09-15 실측 미스에서 추가: 조사·군말 사이 볼륨, 종료 인사 우선, 틀어/시작해
    assert r.route("볼륨 좀 올려줘", True)["media_key"] == "volup"
    assert r.route("볼륨을 팔십까지 올려줘", True)["media_key"] == "volup"
    assert r.route("소리 줄여줄래", True)["media_key"] == "voldown"
    assert r.route("시작해줘", True)["media_key"] == "playpause"
    assert r.route("노래 틀어줘", True)["media_key"] == "playpause"
    assert r.route("크롬 틀어줘", True)["action"] == "open_app"          # 앱 이름이 있으면 열기가 우선
    assert r.route("다음 영상에서 만나요", True)["action"] == "end_session"  # 인사 > 다음영상(next)
    assert r.route("다음 영상", True)["media_key"] == "next"
    assert r.route("수고하셨습니다", True)["action"] == "end_session"
    r.last_logprob = -1.5; assert r.route("다음곡", True) is None; r.last_logprob = None  # 환각 가드: 신뢰도 낮으면 승격
    print("selftest ok")


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        selftest()
    elif "--bench" in sys.argv:  # STT 지연 실측: 2초짜리 무음+톤 오디오로 왕복 시간
        import numpy as np

        r = Router("시아야")
        sr = 16000
        t = np.arange(sr * 2) / sr
        audio = (np.sin(2 * np.pi * 440 * t) * 3000).astype(np.int16)
        for i in range(3):
            text, sec = r.transcribe(audio)
            print(f"{i + 1}회: {sec:.2f}s → {text!r}")
