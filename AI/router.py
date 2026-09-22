# -*- coding: utf-8 -*-
"""1단 로컬 라우터 — 자주 쓰는 고정 명령을 LLM 없이 즉시 액션으로.

로컬 STT(faster-whisper) → 단어 사전 매칭. 사전에 걸리면 LLM 판정과 동일한
스키마의 액션 dict를 반환하고(brain._execute가 그대로 실행), 안 걸리면
None → 호출측이 LLM(2단)으로 승격하며 STT 초안을 힌트로 첨부한다.

승격이 기본인 것들: 지시어("이거") — 화면·시선이 필요, 질문·요약 — answer
생성 필요, 확인 대기 중 발화 — 승인/거부 판정 필요(호출측에서 차단).
1단 범위는 안전한 고정 명령만: 앱 실행, 창 포커스, 화면 캡처, 미디어 제어, 세션 종료.
창 닫기·삭제 같은 파괴적 동작은 확인 흐름이 필요해서 LLM 경로에 남긴다.

모델: 기본 small — GPU(ctranslate2 CUDA) 면 float16·0.15s, 없거나 로드 실패면
CPU int8·2.4s 로 자동 폴백. beam5 + 사전에서 만든 어휘 프롬프트 + 환각 가드
(avg_logprob < STT_MIN_LOGPROB 면 승격). 첫 발화 때 lazy load. 상세 실측은 아래 설정 주석.
NOTE(한계): 매칭은 공백 제거 후 부분 문자열 — 활용형이 사전을 벗어나면
승격된다. 회귀 케이스로 1단 적중률을 실측한 뒤 형태소 분석기(kiwipiepy)
도입을 판단한다.
"""
import difflib
import os
import threading
import re
import time



def _cuda_available():
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception:
        return False


# STT 설정 — 기본 "auto": GPU(ctranslate2 CUDA)가 있으면 small·float16, 없으면 small·int8. beam5·어휘 프롬프트는 공통.
# 실측(eval --tier1 59케이스): base·cpu·beam1 6적중/21미스/중앙 0.70s(9/15 라이브가 이 상태 — '계산결하죠' 식 뭉개짐)
#   → small·cuda 24적중/3미스/0.15s(9/16, 오답 0) · small·cpu·int8·beam5+프롬프트 23적중/4미스/2.4s(오답 0).
# base 는 프롬프트 어휘로 환각('일시정지.' 오답)해 폴백으로도 안 쓴다. CPU small 은 2초대라 느리지만 Gemini 4.5초보다 빠르고 정확하다.
STT_DEVICE = os.environ.get("STT_DEVICE", "auto")
if STT_DEVICE == "auto":
    STT_DEVICE = "cuda" if _cuda_available() else "cpu"
_GPU = STT_DEVICE.startswith("cuda")
MODEL_NAME = os.environ.get("STT_MODEL") or "small"
STT_COMPUTE = os.environ.get("STT_COMPUTE") or ("float16" if _GPU else "int8")
STT_BEAM = int(os.environ.get("STT_BEAM") or 5)
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
# 앱 이름 뒤에 군말만 남으면 열기 — "시아야 메모장 해줄래?"·"시아야 크롬" (실측 미스 2건). "메모장 저장해줘"처럼 다른 동사가 있으면 승격.
APP_ONLY_REQ = {"", "해줘", "해줄래", "해줄래요", "해주세요", "해", "줘", "좀", "좀해줘", "부탁해", "부탁"}
# 앱 이름이 있고 잔여가 열기 동사와 자모 유사하면 열기 — 라이브 실측 "크롬 켜줘"→"크롬 펴줘"(팀원, 9/16).
# 잔여 길이만 보면 "크롬 느려"·"계산기 어디"도 열려서(검토 지적) 유사도를 본다. 다른 의도 표지(닫기·끄기·탭·저장 등)는 승격.
NOT_OPEN = ("닫", "꺼", "끄", "종료", "지워", "삭제", "저장", "탭", "최소", "최대", "이동", "옮", "검색")

# --- 자모 유사도: 동사 초성 오인식(켜줘→펴줘, 띄워→띠워)을 사전 확장 없이 흡수 ---
_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"


def jamo(text):
    """한글 음절을 초·중·종성 문자열로 푼다 — '켜줘' → 'ㅋㅕㅈㅜㅓ'. 한글이 아니면 그대로."""
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(_CHO[code // 588] + _JUNG[code % 588 // 28] + _JONG[code % 28].strip())
        else:
            out.append(ch)
    return "".join(out)


def similar(a, b):
    """자모 단위 difflib 비율 — 켜줘↔펴줘 0.80, 띄워↔띠워 0.80, 켜↔꺼 0.50, 열어↔느려 0.57."""
    return difflib.SequenceMatcher(None, jamo(a), jamo(b)).ratio()


OPEN_SUFFIXES = ("", "줘", "줄래", "봐", "요", "라", "봐줘", "주세요")


def open_like(residual):
    """앱 이름·호출어를 뺀 잔여가 '열기 요청'으로 볼 수 있나 — APP_ONLY_REQ 의 군말이거나, 열기 동사(+군말)와
    자모 유사도 0.7 이상. 검토에서 나온 오탐('크롬 느려'·'크롬은요'·'계산기 어디'·'탐색기 말고')은 전부 0.45 이하."""
    if residual in APP_ONLY_REQ:
        return True
    if len(residual) > 4 or any(x in residual for x in NOT_OPEN):
        return False
    return any(similar(residual, v + suf) >= 0.7 for v in OPEN_VERBS for suf in OPEN_SUFFIXES)  # 켜줘↔펴줘 0.75 가 경계라 여유

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
_KO_DIGIT = {"일": 1, "이": 2, "삼": 3, "사": 4, "오": 5, "육": 6, "칠": 7, "팔": 8, "구": 9}
# 숫자(80·팔십·백) 뒤에 까지/으로/로/퍼센트가 붙거나 문장이 끝나면 절대값 — "볼륨 두 칸 올려"처럼 수량 표현은 안 잡는다.
_LEVEL_RE = re.compile(r"(\d{1,3}|백|[일이삼사오육칠팔구]?십[일이삼사오육칠팔구]?)"
                       r"(?:[가-힣]{1,2}(?:까지|으로|로|퍼센트|프로|%)|(?:까지|으로|로|퍼센트|프로|%|$))")  # "80번지까지"(TTS 실측)도 80


def volume_level(c):
    """압축 문장에서 목표 볼륨 0~100 을 뽑는다. 없으면 None(한 단계 올림·내림).
    팀원 실측(9/16): "소리 80까지 높여줘"가 volup 한 단계로 처리돼 +2 만 올라갔다 → BE volume.set 으로."""
    m = _LEVEL_RE.search(c)
    if not m:
        return None
    tok = m.group(1)
    if tok.isdigit():
        n = int(tok)
    elif tok == "백":
        n = 100
    else:
        tens, ones = tok.split("십")
        n = _KO_DIGIT.get(tens, 1) * 10 + _KO_DIGIT.get(ones, 0)
    return max(0, min(100, n))

# initial_prompt 어휘 힌트 — 사전과 같은 표에서 만들어 항상 동기화. 짧은 한국어 명령의 오인식을 크게 줄인다(위 실측).
DEFAULT_PROMPT = ("시아야. " + " ".join(f"{a} 열어줘. {a} 켜줘." for a in APPS_KO) + " "
                  + " ".join(f"{ws[0]}." for ws, _, _ in MEDIA_KO)
                  + " 볼륨 올려줘. 볼륨 내려줘. 이거 저장해줘. 창 최대화. 다음 탭. 종료.")
STT_PROMPT_FIXED = "STT_PROMPT" in os.environ   # 환경변수로 준 프롬프트는 호출어가 바뀌어도 그대로 쓴다
STT_PROMPT = (os.environ["STT_PROMPT"] or None) if STT_PROMPT_FIXED else DEFAULT_PROMPT

# NOTE(튜닝): 흔한 동사("들어가" 등)는 오탐 실측 후 제거됨 — '유튜브 들어가줄래'가
# end_session 으로 처리된 사례(2026-09-03). 부분 일치는 명시적 종료 표현만.
END_EXACT = ("그만", "끝", "종료")            # 발화 전체가 이것일 때만
END_KO = ("이제그만", "그만해", "이제됐어",    # 부분 일치 허용
          "수고하셨", "수고했", "안녕히", "다음에만나", "다음영상에서만나", "그럼안녕")  # 종료 인사(실측 라벨 end_session)

# 호출어의 STT 흔한 오표기 — 동음·유사 발음만 (실측 기반으로 추가)
# NOTE(튜닝): 미인식↑면 변형을 추가하고, 엉뚱한 발화가 통과하면 뺀다.
# 짧은 변형("시아"·"시야")은 시아버지·시야 같은 일상 단어에 오탐하므로 넣지 않는다
WAKE_VARIANTS = {"시아야": ("시아", "시아야", "시야야", "씨아야")}


def _compact(text):
    return re.sub(r"[^\w]", "", text)


class Router:
    def __init__(self, wake_word):
        self._model = None
        self._load_lock = threading.Lock()
        self._tok = None          # word_logprob 용 토크나이저 — 처음 쓸 때 한 번 만든다
        self._word_tokens = {}    # 단어 → 토큰 후보 (공백 붙인 것, 안 붙인 것)
        self.word, self.wakes, self.prompt = None, (), STT_PROMPT
        self.set_wake(wake_word)

    def set_wake(self, word):
        """호출어가 바뀌면 부른다 — 사전 매칭의 호출어와 받아쓰기 프롬프트 맨 앞의 호출어를 함께 바꾼다.
        프롬프트 맨 앞이 옛 호출어로 남으면 모델이 새 호출어를 옛 호출어로 받아 적는다.
        빈 문자열·공백뿐인 단어는 무시하고 지금 호출어를 유지한다 — 빈 호출어는 사전 매칭이 모든 문장을 호출로 본다."""
        if not word or not word.strip():
            return
        self.word = word
        self.wakes = tuple(_compact(w) for w in WAKE_VARIANTS.get(word, (word,)))
        self.prompt = STT_PROMPT if STT_PROMPT_FIXED else f"{word}." + DEFAULT_PROMPT[len("시아야."):]

    def _load(self, WhisperModel):
        if self._model is not None:
            return
        t0 = time.monotonic()
        self.device, self.compute = STT_DEVICE, STT_COMPUTE
        try:
            if STT_DEVICE.startswith("cuda"):
                import torch  # noqa: F401 — CUDA 빌드 torch 가 cublas64_12/cudnn64_9 DLL 경로를 등록해 ctranslate2 가 GPU 를 잡는다(별도 CUDA 설치 불필요)
            m = WhisperModel(MODEL_NAME, device=STT_DEVICE, compute_type=STT_COMPUTE)
            if STT_DEVICE.startswith("cuda"):
                # cuBLAS·cuDNN 은 모델 생성이 아니라 첫 연산에서 로드된다 — 생성만 보고 GPU 를 채택하면
                # CPU 전용 torch 환경에서 발화마다 "cublas64_12.dll is not found" 로 죽고, self._model 이
                # 이미 차 있어 아래 CPU 폴백이 영영 안 탄다(9/18 팀원 전원 재현: GPU 는 4050~4070 로 멀쩡한데
                # requirements.txt 의 torch==2.11.0 이 PyPI 윈도우 휠이라 CPU 전용이었다).
                import numpy as np

                list(m.transcribe(np.zeros(4000, np.float32), language="ko", beam_size=1)[0])
            self._model = m
        except Exception as e:
            if not STT_DEVICE.startswith("cuda"):
                raise
            # GPU 는 보이는데 쓸 수 없는 환경(CPU 전용 torch 라 cuDNN/cuBLAS DLL 이 없음 등) — 발화마다 수 초짜리
            # 재시도 대신 CPU small 로 한 번에 내려간다. 팀원 노트북 셋업 차이를 여기서 흡수.
            print(f"STT GPU 사용 불가 → CPU 폴백: {str(e)[:120]}")
            self.device, self.compute = "cpu", "int8"
            self._model = WhisperModel(MODEL_NAME, device="cpu", compute_type="int8")
        print(f"STT 모델 로드 ({MODEL_NAME}, {self.device}/{self.compute}, beam {STT_BEAM}, {time.monotonic() - t0:.1f}s)")

    def warm(self):
        """모델 로드 + 무음 1초 추론 — 첫 명령이 로드 1.4s·CUDA 워밍업을 떠안지 않게(팀원 실측 9/16).
        transcribe() 를 거치지 않아 호출 통계를 건드리지 않는다."""
        import numpy as np
        from faster_whisper import WhisperModel

        with self._load_lock:
            self._load(WhisperModel)
        segments, _ = self._model.transcribe(np.zeros(16000, np.float32), language="ko", beam_size=1)
        list(segments)

    def transcribe(self, audio_i16):
        """발화 오디오 → (텍스트, 소요 초, 세그먼트 최저 avg_logprob). 모델은 첫 호출 때 로드."""
        import numpy as np
        from faster_whisper import WhisperModel

        with self._load_lock:  # 예열 스레드와 첫 발화가 겹쳐도 모델은 한 번만 올린다
            self._load(WhisperModel)
        t0 = time.monotonic()
        a = np.asarray(audio_i16, dtype=np.float32) / 32768.0
        segments, _ = self._model.transcribe(a, language="ko", beam_size=STT_BEAM,
                                             condition_on_previous_text=False, initial_prompt=self.prompt)
        segments = list(segments)
        text = "".join(s.text for s in segments).strip()
        logprob = min((s.avg_logprob for s in segments), default=None)
        return text, time.monotonic() - t0, logprob

    def word_logprob(self, audio_i16, word, detail=False):
        """발화에 word 가 들어 있는 정도 → 평균 로그 확률 (0 에 가까울수록 그 단어).

        받아 적게 하지 않고, 같은 모델에게 word 의 글자 조각(토큰)을 강제로 맞춰 보게 해 각 조각의 확률을 읽는다.
        받아쓰기로 확인하면 짧은 단독 호출을 인사말("잘했어요" 등)로 바꿔 적어 실제 호출 41개 중 28개만 통과했고,
        단어 확률로는 37개가 통과했다. 무관한 말은 두 방식 모두 0건이었다.
        프롬프트는 주지 않는다 — 받아쓰기 확인에서 프롬프트가 결과를 호출어 쪽으로 끌어 다른 호출어("시아야")의
        오통과를 늘렸다. 단어 앞 공백 유무에 따라 토큰이 달라 두 후보 중 높은 값을 쓴다.

        detail=True 면 (평균, 마지막 조각) 을 돌려준다. 끝음절이 빠진 말("철수야" 에 대한 "철수")은 앞 조각이 잘 맞아
        평균으로는 묻히고 마지막 조각만 폭락한다 — 실측 예 [-0.12, -0.00, -0.07, -11.27], 평균 -2.87."""
        import numpy as np
        from faster_whisper import WhisperModel
        from faster_whisper.audio import pad_or_trim

        if not word or not word.strip():
            raise ValueError("확인할 단어가 비어 있습니다")
        with self._load_lock:
            self._load(WhisperModel)
            cands = self._word_tokens.get(word)
            if cands is None:
                if self._tok is None:
                    from faster_whisper.tokenizer import Tokenizer

                    m = self._model
                    self._tok = Tokenizer(m.hf_tokenizer, m.model.is_multilingual, task="transcribe", language="ko")
                cands = self._word_tokens[word] = (self._tok.encode(" " + word), self._tok.encode(word))
        m = self._model
        f = m.feature_extractor(np.asarray(audio_i16, np.float32) / 32768.0)
        enc = m.encode(pad_or_trim(f))
        frames = min(f.shape[-1], 3000)   # 인코더는 30 s(3000프레임)까지만 본다 — 그보다 긴 발화는 앞 30 s 만 맞춘다

        def lp(c):
            p = m.model.align(enc, self._tok.sot_sequence, [c], frames)[0].text_token_probs[:len(c)]   # 끝의 종료 토큰은 뺀다
            return np.log(np.maximum(np.asarray(p), 1e-9))

        best = max((lp(c) for c in cands), key=lambda v: v.mean())
        return (float(best.mean()), float(best[-1])) if detail else float(best.mean())

    def _residual(self, c, name):
        """호출어·앱 이름을 뺀 나머지 — 군말뿐인지 판단용."""
        r = c.replace(name, "")
        for w in sorted(self.wakes, key=len, reverse=True):
            r = r.replace(w, "")
        return r

    def route(self, text, session_active, logprob):
        """텍스트 → 액션 dict 또는 None(승격). 게이트: 호출어 또는 활성 세션."""
        if not text:
            return None
        if logprob is not None and logprob < STT_MIN_LOGPROB:
            return None  # 전사 신뢰도 낮음(환각 의심) — 즉시 실행 대신 LLM 승격
        c = _compact(text)
        if any(_compact(d) in c for d in DEICTIC) or any(a in c for a in ASK):
            return None  # 화면·생성이 필요 — LLM 몫
        wake = any(w in c for w in self.wakes)
        if not (wake or session_active):
            return None  # 호출어도 세션도 없음 — 기각 판단은 LLM이 (오인식 방어)

        base = {"audio_is_speech": True, "wake_heard": wake, "is_command": True,
                "transcript": text, "tier": 1}
        request = c
        for w in sorted(self.wakes, key=len, reverse=True):
            if request.startswith(w):
                request = request[len(w):]
                break
        # NOTE(튜닝): 창 전환은 고정 표현만 처리 — 표현 확장은 실측 미스가 생기면 추가한다(-353).
        focus = re.fullmatch(
            r"(?:(크롬)에서)?(유튜브|youtube)(?:를)?(?:좀)?"
            r"(?:띄워(?:줘|주세요|줄래)?|앞으로(?:가져와|가져다줘))",
            request, re.IGNORECASE) or re.fullmatch(
            r"(?:(크롬)에서)?(.+?)(?:창(?:을)?(?:좀)?"
            r"(?:띄워|보여|열어)(?:줘|주세요|줄래)?|(?:창(?:을)?)?(?:좀)?앞으로(?:가져와|가져다줘))",
            request, re.IGNORECASE)
        if focus:
            name = focus[2]
            if name.endswith(("을", "를")) and name[:-1] in APPS_KO:
                name = name[:-1]
            return {**base, "action": "window", "window_op": "focus", "query": name,
                    "app": APPS_KO.get(focus[1]), "say": f"{name} 창을 띄웠습니다"}
        if re.fullmatch(r"(?:전체)?화면(?:을)?(?:좀)?(?:캡처|캡쳐)(?:해줘|해줄래|해주세요)?|스크린샷(?:찍어줘|저장해줘)?", request):
            return {**base, "action": "capture", "capture_scope": "screen", "say": "화면을 캡처했습니다"}
        if request in ("세션취소", "세션취소해줘", "명령취소", "명령취소해줘", "취소", "취소해줘"):
            return {**base, "action": "end_session", "say": "대기 모드로 전환합니다"}
        for name, key in APPS_KO.items():
            if name not in c:
                continue
            r = re.sub(r"^[을를]", "", self._residual(c, name)).replace("좀", "")
            if open_like(r):
                return {**base, "action": "open_app", "app": key,
                        "say": f"{name}를 열게요"}
            return None  # 앱 이름 외에 검색어·창 조작이 남으면 승격 — 앱 실행으로 삼키지 않는다(-353).
        # 종료 인사는 미디어보다 먼저 — "다음 영상에서 만나요"가 '다음 영상'(next)으로 잡히지 않게
        if session_active and (c in END_EXACT or any(e in c for e in END_KO)):
            return {**base, "action": "end_session", "say": "대기 모드로 전환합니다"}
        for words, key, say in MEDIA_KO:
            if any(_compact(w) in c for w in words):
                return {**base, "action": "media", "media_key": key, "say": say}
        if any(n in c for n in VOL_NOUNS):
            level = volume_level(c)
            if level is not None:  # 절대값은 BE volume.set — 한 단계 키 입력으론 80 을 못 맞춘다
                return {**base, "action": "media", "media_key": "volset", "level": level,
                        "say": f"볼륨을 {level}으로 맞출게요"}
            if any(v in c for v in VOL_UP):
                return {**base, "action": "media", "media_key": "volup", "say": "볼륨을 올릴게요"}
            if any(v in c for v in VOL_DOWN):
                return {**base, "action": "media", "media_key": "voldown", "say": "볼륨을 내릴게요"}
        return None


def selftest():
    r = Router("시아야")
    hit = r.route("시아야 계산기 열어줘", False, None)
    assert hit and hit["action"] == "open_app" and hit["app"] == "calc" and hit["wake_heard"]
    hit = r.route("음소거 해줘", True, None)  # 세션 중엔 호출어 없이도
    assert hit and hit["action"] == "media" and hit["media_key"] == "mute"
    assert r.route("계산기 열어줘", False, None) is None       # 호출어도 세션도 없음 → 승격
    assert r.route("시아야 이거 저장해줘", False, None) is None  # 지시어 → 승격
    assert r.route("시아야 이 문서 요약해줘", False, None) is None  # 생성 필요 → 승격
    assert r.route("시아야 아까 그 파일 다시 띄워봐", False, None) is None  # 사전 밖 → 승격
    hit = r.route("이제 그만", True, None)
    assert hit and hit["action"] == "end_session"
    assert r.route("그만", False, None) is None  # 세션 없는 '그만'은 승격
    # 2026-09-15 실측 미스에서 추가: 조사·군말 사이 볼륨, 종료 인사 우선, 틀어/시작해
    assert r.route("볼륨 좀 올려줘", True, None)["media_key"] == "volup"
    assert r.route("볼륨을 팔십까지 올려줘", True, None)["media_key"] == "volset"  # 값이 있으면 절대값(9/16 팀원 실측)
    assert r.route("소리 줄여줄래", True, None)["media_key"] == "voldown"
    assert r.route("시작해줘", True, None)["media_key"] == "playpause"
    assert r.route("노래 틀어줘", True, None)["media_key"] == "playpause"
    assert r.route("크롬 틀어줘", True, None)["action"] == "open_app"          # 앱 이름이 있으면 열기가 우선
    assert r.route("시아야 메모장 해줄래?", False, None)["app"] == "notepad"   # 앱 이름 + 군말 → 열기(실측 미스)
    assert r.route("메모장 해줄래?", True, None)["action"] == "open_app"
    assert r.route("시아야 크롬", False, None)["action"] == "open_app"
    assert r.route("메모장 저장해줘", True, None) is None                     # 다른 동사 → 승격
    assert r.route("시아야 크롬 펴줘", False, None)["app"] == "chrome"        # 동사 오인식(켜줘→펴줘) — 앱 이름이 닻
    assert r.route("시아야 크롬 닫아줘", False, None) is None                 # 닫기 표지 → 승격
    assert r.route("크롬 탭 닫아", True, None) is None
    assert r.route("메모장에 적어줘", True, None) is None                     # 열기와 무관한 동사 → 승격
    assert r.route("메모장 띠워줘", True, None)["app"] == "notepad"          # 띄워→띠워(자모 0.8)
    for bad in ("크롬 느려", "크롬은요", "계산기 어디", "탐색기 말고", "크롬 봐", "크롬이 안 돼"):
        assert r.route(bad, True, None) is None, bad                       # 검토 지적: 짧은 잔여만으로 열면 오탐
    assert similar("켜줘", "펴줘") >= 0.7 and similar("켜", "꺼") < 0.7
    hit = r.route("소리 80까지 높여줘", True, None)                           # 절대값(팀원 실측: 한 단계만 올라감)
    assert hit["media_key"] == "volset" and hit["level"] == 80
    assert r.route("볼륨을 팔십으로 맞춰줘", True, None)["level"] == 80
    assert r.route("볼륨 십오", True, None)["level"] == 15 and r.route("소리 백으로", True, None)["level"] == 100
    assert r.route("볼륨 두 칸 올려줘", True, None)["media_key"] == "volup"     # 수량 표현은 한 단계
    assert r.route("소리 80번지까지 높여줘", True, None)["level"] == 80          # 숫자·조사 사이 군말(TTS 실측)
    assert r.route("볼륨 3 올려", True, None)["media_key"] == "volup"           # 조사 없는 숫자는 절대값이 아니다
    assert r.route("볼륨 올려줘", True, None)["media_key"] == "volup"
    assert r.route("다음 영상에서 만나요", True, None)["action"] == "end_session"  # 인사 > 다음영상(next)
    assert r.route("다음 영상", True, None)["media_key"] == "next"
    assert r.route("수고하셨습니다", True, None)["action"] == "end_session"
    assert r.route("다음곡", True, -1.5) is None  # 환각 가드: 신뢰도 낮으면 승격
    # 호출어 변경 — 사전 매칭과 프롬프트 맨 앞이 새 호출어를 따른다 (STT_PROMPT 환경변수가 없을 때)
    r.set_wake("철수야")
    assert r.wakes == ("철수야",)
    assert STT_PROMPT_FIXED or r.prompt.startswith("철수야. ")
    hit = r.route("철수야 계산기 열어줘", False, None)
    assert hit and hit["action"] == "open_app" and hit["wake_heard"]
    assert r.route("시아야 계산기 열어줘", False, None) is None               # 옛 호출어로는 세션 밖에서 안 잡힌다
    r.set_wake("시아야")
    assert r.prompt == STT_PROMPT and (STT_PROMPT_FIXED or r.prompt == DEFAULT_PROMPT)   # "시아야"면 글자까지 그대로
    assert r.wakes == WAKE_VARIANTS["시아야"]
    r.set_wake("  "); assert r.word == "시아야" and r.route("계산기 열어줘", False, None) is None  # 빈 호출어는 무시 — 모든 문장이 호출이 되면 안 된다

    # GPU 채택 판정: 생성이 아니라 "첫 연산까지" 통과해야 한다. cuBLAS 는 지연 로드라
    # 생성은 DLL 이 없어도 늘 성공하고, 그때 GPU 를 채택해 버리면 폴백이 영영 안 탄다(9/18).
    class _FakeWhisper:
        broken_gpu = True  # cuda 일 때만 첫 연산에서 터진다 — 실제 cuBLAS 누락과 같은 모양

        def __init__(self, name, device="cpu", compute_type="int8"):
            self.device = device

        def transcribe(self, *a, **k):
            if self.device.startswith("cuda") and _FakeWhisper.broken_gpu:
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
            return iter(()), None

    g = globals()
    saved = (g["STT_DEVICE"], g["STT_COMPUTE"])
    try:
        g["STT_DEVICE"], g["STT_COMPUTE"] = "cuda", "float16"
        broken = Router("시아야")
        broken._load(_FakeWhisper)
        assert (broken.device, broken.compute) == ("cpu", "int8"), (broken.device, broken.compute)
        assert broken._model.device == "cpu"          # 폴백 모델로 교체됐다 (망가진 cuda 모델을 들고 있지 않다)
        _FakeWhisper.broken_gpu = False
        good = Router("시아야")
        good._load(_FakeWhisper)
        assert (good.device, good.compute) == ("cuda", "float16"), (good.device, good.compute)
    finally:
        _FakeWhisper.broken_gpu = True
        g["STT_DEVICE"], g["STT_COMPUTE"] = saved
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
            text, sec, logprob = r.transcribe(audio)
            print(f"{i + 1}회: {sec:.2f}s lp={logprob} → {text!r}")
