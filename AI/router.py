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

MODEL_NAME = os.environ.get("STT_MODEL", "base")

# 화면·시선이 필요한 지시어 — 1단이 절대 처리하면 안 됨
DEICTIC = ("이거", "저거", "그거", "여기", "저기", "이 창", "이 파일", "이걸", "그걸")
# answer 생성이 필요한 발화 표지 — LLM 몫
ASK = ("뭐야", "뭐지", "뭔데", "설명", "요약", "번역", "알려줘", "어때")

APPS_KO = {"계산기": "calc", "메모장": "notepad", "크롬": "chrome",
           "탐색기": "explorer", "그림판": "paint"}
OPEN_VERBS = ("열어", "켜", "띄워", "실행")

MEDIA_KO = [  # (키워드들, media_key, say)
    (("음소거", "소리꺼", "소리켜"), "mute", "음소거를 전환할게요"),
    (("일시정지", "일시 정지", "멈춰", "재생"), "playpause", "재생을 전환할게요"),
    (("다음곡", "다음 곡", "다음영상", "다음 영상", "다음노래"), "next", "다음으로 넘길게요"),
    (("이전곡", "이전 곡", "이전영상", "이전 영상", "이전노래"), "prev", "이전으로 돌릴게요"),
    (("볼륨올려", "볼륨 올려", "소리키워", "소리 키워", "볼륨업"), "volup", "볼륨을 올릴게요"),
    (("볼륨내려", "볼륨 내려", "볼륨줄여", "볼륨 줄여", "소리줄여", "소리 줄여"), "voldown", "볼륨을 내릴게요"),
]

END_KO = ("그만", "이제 됐어", "이제됐어", "들어가", "쉬어")


def _compact(text):
    return re.sub(r"[^\w]", "", text)


class Router:
    def __init__(self, wake_word):
        self.wake = _compact(wake_word)
        self._model = None

    def transcribe(self, audio_i16):
        """발화 오디오 → (텍스트, 소요 초). 모델은 첫 호출 때 로드."""
        import numpy as np
        from faster_whisper import WhisperModel

        if self._model is None:
            t0 = time.monotonic()
            self._model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
            print(f"STT 모델 로드 ({MODEL_NAME}, {time.monotonic() - t0:.1f}s)")
        t0 = time.monotonic()
        a = np.asarray(audio_i16, dtype=np.float32) / 32768.0
        segments, _ = self._model.transcribe(a, language="ko", beam_size=1,
                                             condition_on_previous_text=False)
        text = "".join(s.text for s in segments).strip()
        return text, time.monotonic() - t0

    def route(self, text, session_active):
        """텍스트 → 액션 dict 또는 None(승격). 게이트: 호출어 또는 활성 세션."""
        if not text:
            return None
        c = _compact(text)
        if any(_compact(d) in c for d in DEICTIC) or any(a in c for a in ASK):
            return None  # 화면·생성이 필요 — LLM 몫
        wake = self.wake in c
        if not (wake or session_active):
            return None  # 호출어도 세션도 없음 — 기각 판단은 LLM이 (오인식 방어)

        base = {"audio_is_speech": True, "wake_heard": wake, "is_command": True,
                "transcript": text, "tier": 1}
        for name, key in APPS_KO.items():
            if name in c and any(v in c for v in OPEN_VERBS):
                return {**base, "action": "open_app", "app": key,
                        "say": f"{name}를 열게요"}
        for words, key, say in MEDIA_KO:
            if any(_compact(w) in c for w in words):
                return {**base, "action": "media", "media_key": key, "say": say}
        if session_active and any(_compact(e) in c for e in END_KO):
            return {**base, "action": "end_session", "say": "대기 모드로 전환합니다"}
        return None


def selftest():
    r = Router("자비스")
    hit = r.route("자비스 계산기 열어줘", False)
    assert hit and hit["action"] == "open_app" and hit["app"] == "calc" and hit["wake_heard"]
    hit = r.route("음소거 해줘", True)  # 세션 중엔 호출어 없이도
    assert hit and hit["action"] == "media" and hit["media_key"] == "mute"
    assert r.route("계산기 열어줘", False) is None       # 호출어도 세션도 없음 → 승격
    assert r.route("자비스 이거 저장해줘", False) is None  # 지시어 → 승격
    assert r.route("자비스 이 문서 요약해줘", False) is None  # 생성 필요 → 승격
    assert r.route("자비스 아까 그 파일 다시 띄워봐", False) is None  # 사전 밖 → 승격
    hit = r.route("이제 그만", True)
    assert hit and hit["action"] == "end_session"
    assert r.route("그만", False) is None  # 세션 없는 '그만'은 승격
    print("selftest ok")


if __name__ == "__main__":
    import sys

    if "--selftest" in sys.argv:
        selftest()
    elif "--bench" in sys.argv:  # STT 지연 실측: 2초짜리 무음+톤 오디오로 왕복 시간
        import numpy as np

        r = Router("자비스")
        sr = 16000
        t = np.arange(sr * 2) / sr
        audio = (np.sin(2 * np.pi * 440 * t) * 3000).astype(np.int16)
        for i in range(3):
            text, sec = r.transcribe(audio)
            print(f"{i + 1}회: {sec:.2f}s → {text!r}")
