# -*- coding: utf-8 -*-
"""상시 음성 대기.

에너지 기반 VAD(적응 노이즈 임계)로 발화를 잘라낸다. STT는 여기서 하지 않는다 —
오디오 원본을 Gemini에 화면과 함께 그대로 보내는 융합 콜 구조이므로,
이 모듈의 책임은 "언제부터 언제까지가 발화인가"와 **발화 시작 시각**뿐이다.
(시작 시각이 중요한 이유: 그 순간의 응시 위치를 링버퍼에서 조회해야 하므로.)

이벤트 큐로 내보내는 것:
  ("onset", t)          — 발화 시작 감지 (이 순간 화면·응시를 캡처할 것)
  ("utter", t, audio)   — 발화 종료, int16 mono 오디오 전체
  ("reset", t)          — 장치 전환·입력 중단, 이전 발화의 화면 캡처 폐기
  ("wake_live", t, 점수, 절단여부) — 상시 추론이 호출어를 잡음. 절단여부 = 앞서 열린 조각의 앞을 잘랐는지
  ("notice", message)   — 마이크 실패 안내, BE에는 notice {message}로 전달
"""
import ctypes
import sys
import threading
import time
from contextlib import closing
from functools import cache

import numpy as np

SR = 16000
BLOCK = 480  # 30ms
MIC_STALL_S = 3.0         # NOTE(튜닝): 입력이 이 시간 동안 없으면 장치 중단으로 보고 복구한다.
MIC_RETRY_S = 1.0         # NOTE(튜닝): 기본 장치도 실패했을 때 첫 재시도 간격. 이후 두 배씩 늘린다.
MIC_RETRY_MAX_S = 15.0    # NOTE(튜닝): 복구 지연과 반복 시도 부하 사이의 백오프 상한.
MIC_OVERFLOW_LOG_S = 15.0  # NOTE(튜닝): CPU 부하로 오버플로가 반복돼도 로그는 이 간격으로 제한한다.


class VadSegmenter:
    """블록 단위 RMS로 발화 구간을 자르는 순수 로직 (테스트 가능).

    NOTE(한계): 에너지 VAD — 조용한 실내 기준. 시끄러운 환경이 문제 되면
    webrtcvad/실크 VAD로 교체할 것.
    """

    def __init__(self, sr=SR, block=BLOCK, start_blocks=3, end_silence_s=0.55,
                 preroll_s=2.0, max_s=12.0, min_speech_s=0.35, floor=350.0,
                 noise_win_s=40.0, noise_pct=80.0, ratio=1.5, ratio_lo=1.0, tail_s=0.3):
        # start 3블록(90ms)+프리롤 2.0초 — 호출어 첫 음절이 잘리면 명령 전체가 기각되므로 시작은 후하게 잡는다.
        # (2 → 3 블록: 유튜브 오탐 −30% 에 검출 −0~1 — 가장 싼 레버)
        # 노이즈 바닥 = 최근 noise_win_s 초 블록 rms 의 noise_pct 백분위, **녹음 중에도** 매 블록 갱신.
        # 유튜브처럼 임계를 넘는 배경이 계속되면 옛 방식(임계 아래·비녹음 블록에서만 EMA)은 바닥이 얼어붙어
        # 12초 상한 덩어리를 연달아 자르고 호출을 그 안에 삼킨다. 최솟값·하위 분위는 말소리 사이 틈을 재서 소용없다.
        # 창 40 s: 본인 말이 창의 20% 를 못 채워야 바닥이 본인 레벨로 안 뜬다 (20 s 는 4 s 발화 뒤 후속 호출을 놓쳤다).
        # 조용한 곳에선 바닥×ratio < floor 라 임계 = floor 350, 옛 동작과 같다. noise_win_s=0 이면 옛 EMA (비교용).
        # 유지 임계 = 바닥×ratio_lo (시작보다 낮게), 녹음 중 직전 유성 뒤 tail_s 안에서만 듣는다 — 문장 꼬리·약음절에서 안 끊긴다.
        # 프리롤 2.0: 배경 위에서 호출어 첫 음절 보존 (시험지 앞잘림 p90 380 → 0 ms, 온전히 잡힌 발화 169 → 193/240).
        # 프리롤이 길어져 붙는 배경은 시동어 게이트(brain.py WAKE_LEAD_TRIM_S)가 다시 떼고 채점하고, 화자 게이트는 크롭(107)이 잘라낸다.
        self.block_dur = block / sr
        self.ratio = ratio
        self.ratio_lo = ratio_lo or ratio
        self.tail_blocks = int(tail_s / self.block_dur)
        self.noise_win = int(noise_win_s / self.block_dur)
        self.noise_pct = noise_pct
        # 바닥 창은 고정 배열 + 헤드 인덱스 원형 버퍼 — deque 는 np.percentile 때마다 파이썬 객체 1333개를 배열로 복사한다 (블록당 0.087 → ~0.04 ms).
        # float64 유지: float32 면 백분위 보간이 마지막 비트에서 달라져 임계 경계 블록의 판정이 뒤집힐 수 있다.
        self._ring = np.zeros(max(self.noise_win, 1))
        self._ring_i = 0   # 다음에 쓸 칸 (끝에 닿으면 0 — 가장 오래된 값을 덮어쓴다)
        self._ring_n = 0   # 채워진 개수 (첫 40 s 동안만 창보다 작다)
        self.start_blocks = start_blocks
        self.end_blocks = int(end_silence_s / self.block_dur)
        self.preroll_n = int(preroll_s / self.block_dur)
        self.max_blocks = int(max_s / self.block_dur)
        self.min_speech_blocks = int(min_speech_s / self.block_dur)
        self.floor = floor
        self.noise = floor
        self.last_rms = 0.0  # 마지막 블록 rms — 시동어 점수 줄에 같이 찍어 "조각이 왜 안 열렸나" 를 가른다
        self.recording = False
        self._preroll = []
        self._buf = []
        self._hot = 0
        self._quiet = 0
        self._speech = 0
        self._since = 0   # 마지막 유성(시작 임계 초과) 뒤 블록 수
        self._onset_t = 0.0

    @property
    def threshold(self):
        return max(self.noise * self.ratio, self.floor)

    @property
    def threshold_lo(self):
        """유지 임계 (녹음 중). 시작 임계보다 높아지지 않게 묶는다."""
        return max(self.noise * min(self.ratio_lo, self.ratio), self.floor)

    @property
    def onset_t(self):
        """지금 열려 있는(또는 마지막) 조각의 시작 시각 — 호출어를 잡은 시각과 견주는 쪽이 쓴다."""
        return self._onset_t

    def feed(self, block_i16, t):
        """블록 하나 투입. 반환: None | ("onset", t) | ("utter", t_onset, audio)."""
        rms = float(np.sqrt(np.mean(block_i16.astype(np.float32) ** 2)))
        self.last_rms = rms
        if self.noise_win:
            self._ring[self._ring_i] = rms
            self._ring_i = (self._ring_i + 1) % self.noise_win
            self._ring_n = min(self._ring_n + 1, self.noise_win)
            self.noise = float(np.percentile(self._ring[:self._ring_n], self.noise_pct))  # 순서 무관이라 링을 그대로 넣는다
        if not self.recording:
            self._preroll.append(block_i16)
            self._preroll = self._preroll[-self.preroll_n:]
            if rms > self.threshold:
                self._hot += 1
            else:
                self._hot = 0
                if not self.noise_win:  # 옛 방식 (비교용) — 조용할 때만 갱신
                    self.noise = 0.97 * self.noise + 0.03 * rms
            if self._hot >= self.start_blocks:
                self.recording = True
                self._buf = list(self._preroll)
                self._preroll = []  # 링은 녹음 중엔 안 채워지므로 비운다 — 안 비우면 직전 조각 종료 후 preroll_s 안에
                # 열린 조각 앞에 직전 녹음 이전의 옛 오디오가 붙어 시간이 끊긴다 (유튜브 12초 상한 연속 절단 때 거의 매 조각).
                self._hot = 0
                self._quiet = 0
                self._speech = self.start_blocks
                self._since = 0
                self._onset_t = t - self.start_blocks * self.block_dur
                return ("onset", self._onset_t)
            return None
        # 녹음 중
        self._buf.append(block_i16)
        if rms > self.threshold:
            self._quiet = 0
            self._speech += 1
            self._since = 0
        elif rms > self.threshold_lo and self._since < self.tail_blocks:
            self._quiet = 0   # 말 꼬리. 유성 계수(_speech)는 시작 임계로만 센다 — 낮은 임계로 세면 짧은 소음이 발화가 된다
            self._since += 1
        else:
            self._quiet += 1
            self._since += 1
        if self._quiet >= self.end_blocks or len(self._buf) >= self.max_blocks:
            self.recording = False
            buf, self._buf = self._buf, []
            if self._speech >= self.min_speech_blocks:
                return ("utter", self._onset_t, np.concatenate(buf))
            return None  # 너무 짧음 (기침, 소음) — 버림
        return None

    def cut(self, t_now, keep_s):
        """녹음 중인 조각의 앞을 버리고 마지막 keep_s 초만 남긴다 — 배경이 먼저 연 조각에서 호출어가
        잡히면 그 앞은 배경이고, 화자 대조 구간에 딸려 들어가면 안 된다. 노이즈 바닥 창은 그대로 둔다."""
        if not self.recording:
            return
        n = max(int(keep_s / self.block_dur), 1)
        self._buf = self._buf[-n:]
        self._onset_t = t_now - len(self._buf) * self.block_dur
        self._speech = min(self._speech, len(self._buf))  # 버린 구간의 유성 계수는 함께 버린다


WAKE_STREAM_DEBOUNCE_S = 1.5   # NOTE(튜닝): 같은 호출을 이웃 블록에서 여러 번 잡지 않게 두는 간격.
WAKE_STREAM_LO = 0.3           # NOTE(튜닝): 하한. 주 임계엔 못 미쳐도 이 위면 "부른 것 같다"로 보고 민감 상태를 켠다. 아직 안 잰 초기값.
WAKE_STREAM_SENSITIVE_S = 3.0  # NOTE(튜닝): 민감 상태 길이 — 그 안에 다시 부르면 하한만 넘어도 잡는다.
WAKE_STREAM_REARM_S = 0.7      # NOTE(튜닝): 첫 상승 뒤 이 간격 안의 재상승은 같은 한 마디의 점수 흔들림으로 보고 무시한다
                               # (호출어 한 마디가 0.6~0.8 s — 그보다 짧으면 다시 부른 것이 아니다).
WAKE_CUT_S = 1.5               # NOTE(튜닝): 호출어가 잡혔을 때 조각이 이보다 먼저 열려 있었으면 배경이 연 조각으로 보고 앞을 자른다.
                               # 호출은 조각 시작 뒤 중앙 0.94 s·p90 1.89 s 에 잡혔다 (유튜브 배경 실녹음 36건) — 남기는 길이도 같은 값.
WAKE_FOLLOW_S = 3.0            # NOTE(튜닝): 호출어 히트 뒤 이 시간 안에 시작한 조각은 세션이 아직 안 열렸어도 brain 에 넘긴다.
                               # "시아야 (쉬고) 음소거" 처럼 둘로 잘린 둘째 조각이 첫 조각 처리 중에 도착하면 사전 필터가
                               # 버리던 것. 세션을 여는 게 아니라 brain 게이트(세션 안 / 호출어)는 그대로 지난다.


class WakeStream:
    """마이크 블록을 시동어 모델에 그대로 흘려 호출어를 말하는 도중에 잡는다.

    여기서 잡힌 시각이 발화 시작의 기준이다 — 세션 밖에서 히트가 없는 조각은 assistant 가 brain 에
    넘기기 전에 버리고, 히트보다 훨씬 전에 열린 조각은 앞을 자른다(WAKE_CUT_S). 발화를 통째로
    채점하는 기존 경로(brain.wake_score_of)는 그대로 한 번 더 돈다 — 2차 확인.
    블록(480 샘플)을 그대로 넣는다 — 모델이 안에서 1280 샘플을 모아 처리하고, 비용도 모아 넣을 때와 같다 (코어 하나의 2.9 %).
    """

    def __init__(self, model, key, threshold=0.5, debounce_s=WAKE_STREAM_DEBOUNCE_S,
                 threshold_lo=WAKE_STREAM_LO, sensitive_s=WAKE_STREAM_SENSITIVE_S):
        self.model = model
        self.key = key            # 모델 파일 이름(siaya_v1) — predict 가 이 이름으로 점수를 돌려준다
        self.threshold = threshold
        self.threshold_lo = min(threshold_lo, threshold)
        self.sensitive_s = sensitive_s
        self.debounce_s = debounce_s
        self.last_score = 0.0
        self._prev = 0.0
        self._last_hit = float("-inf")
        self._sensitive_until = float("-inf")
        self._armed_at = float("-inf")   # 민감 상태를 켠 첫 상승의 시각 — 같은 마디의 흔들림을 걸러내는 기준

    def feed(self, block_i16, t):
        """블록 하나 투입. 반환: None | ("wake_live", t, score)."""
        score = float(self.model.predict(block_i16)[self.key])
        rising = self._prev < self.threshold_lo <= score  # 하한을 새로 넘어선 순간 = 새로 부른 것
        self._prev, self.last_score = score, score
        # 라이브러리의 debounce_time 은 한 번에 넣은 샘플 수로 프레임 수를 환산한다. 블록을 그대로
        # 넣는 지금은 그 수가 들쭉날쭉해 간격이 흔들리므로, 시각으로 직접 재는 편이 확실하다.
        if t - self._last_hit < self.debounce_s:
            return None
        again = rising and self._armed_at + WAKE_STREAM_REARM_S <= t < self._sensitive_until
        if score >= self.threshold or again:
            self._last_hit = t
            self._sensitive_until = float("-inf")
            return ("wake_live", t, round(score, 3))
        if rising and t >= self._sensitive_until:
            # 주 임계 미달 — 같은 호출을 낮은 임계로 다시 재지 않고(오탐이 그대로 하한까지 내려간다),
            # 잠시 뒤 다시 부르는 것만 하한으로 받는다. 창 안의 이른 재상승은 같은 마디의 흔들림이라 여기 안 온다.
            self._armed_at = t
            self._sensitive_until = t + self.sensitive_s
        return None

    def reset(self):
        """장치 전환·오버플로로 오디오가 끊기면 모델 안에 남은 앞 문맥을 버린다."""
        self.model.reset()
        self.last_score = self._prev = 0.0
        self._last_hit = self._sensitive_until = self._armed_at = float("-inf")


@cache
def _wasapi_dlls(libname):
    """장치 조회마다 LoadLibrary 참조가 쌓이지 않도록 DLL 핸들을 재사용한다."""
    return ctypes.CDLL(libname), ctypes.WinDLL("ole32")


def wasapi_endpoint_id(sd, index):
    """PortAudio 소유 IMMDevice의 ID 조회 — GetId가 할당한 문자열만 해제한다."""
    if sys.platform != "win32":
        raise OSError("Core Audio 장치 ID는 Windows에서만 지원합니다")
    # 공개 API로는 엔드포인트 ID 조회·장치 재검색이 안 되어 sounddevice 0.5.6의 사설 API를 사용한다.
    dll, ole = _wasapi_dlls(sd._libname)
    get_device = dll.PaWasapi_GetIMMDevice
    get_device.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
    get_device.restype = ctypes.c_int
    ole.CoInitializeEx.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    ole.CoInitializeEx.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    hr = ole.CoInitializeEx(None, 0)
    if hr < 0 and hr != -2147417850:  # RPC_E_CHANGED_MODE: 기존 STA에서도 조회할 수 있다.
        raise OSError(f"CoInitializeEx: {hr}")
    value = ctypes.c_void_p()
    try:
        device = ctypes.c_void_p()
        if get_device(index, ctypes.byref(device)) != 0 or not device:
            raise OSError("WASAPI 장치 ID 조회 실패")
        table = ctypes.cast(device, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        get_id = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                                   ctypes.POINTER(ctypes.c_void_p))(table[5])
        if get_id(device, ctypes.byref(value)) < 0 or not value:
            raise OSError("IMMDevice.GetId 실패")
        return ctypes.wstring_at(value)
    finally:
        if value:
            ole.CoTaskMemFree(value)
        # PaWasapi_GetIMMDevice는 AddRef하지 않는다 — 빌린 포인터를 Release하면 안 된다.
        if hr >= 0:
            ole.CoUninitialize()


def resolve_input_device(sd, device_id):
    """엔드포인트 ID를 정확히 대조한다 — PortAudio의 장치 이름 부분 일치로 넘기지 않는다."""
    hosts = sd.query_hostapis()
    if device_id is None:
        return next((h["default_input_device"] for h in hosts
                     if h["name"] == "Windows WASAPI" and h["default_input_device"] >= 0),
                    sd.default.device[0])
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValueError("잘못된 마이크 장치 ID")
    matches = []
    for index, info in enumerate(sd.query_devices()):
        if info["max_input_channels"] <= 0 or hosts[info["hostapi"]]["name"] != "Windows WASAPI":
            continue
        if wasapi_endpoint_id(sd, index).casefold() == device_id.casefold():
            matches.append(index)
    if len(matches) != 1:
        raise OSError("선택한 마이크를 찾을 수 없거나 장치 ID가 모호합니다")
    return matches[0]


class VoiceListener(threading.Thread):
    """마이크 전용 스레드 — VadSegmenter 이벤트를 out_queue로 흘린다."""

    def __init__(self, out_queue, device=None, on_reset=None, wake_stream=None, cut_ok=None):
        super().__init__(daemon=True)
        self.out_queue = out_queue
        self.device = device
        self.seg = VadSegmenter()
        self.wake_stream = wake_stream  # WakeStream 또는 None (시동어 모델이 없을 때 — 조각 완성 뒤 채점하는 예전 경로)
        self.cut_ok = cut_ok      # 조각 시작 시각 → 앞을 잘라도 되는지 답하는 함수. 없으면 항상 자른다.
        self.running = True
        self.error = None
        self.on_reset = on_reset
        self._selection = ("native", device)
        self._lock = threading.Lock()
        self._changed = threading.Event()
        self._generation = 0
        self._reported = set()
        self._last_overflow_log = float("-inf")

    def set_settings(self, settings):
        """키 누락은 현재 입력 유지, 명시적 null은 시스템 기본 마이크 선택."""
        if not isinstance(settings, dict) or "micDeviceId" not in settings:
            return False
        selection = ("endpoint", settings["micDeviceId"])
        with self._lock:
            if selection == self._selection or (selection[1] is None and self._selection[1] is None):
                return False
            self._selection = selection
            self._reported.clear()
            self._reset()
            self._changed.set()
        return True

    def _reset(self):
        """잠금 안에서 호출 — 이전 발화와 연결된 화면 캡처까지 폐기한다."""
        self._generation += 1
        self.seg = VadSegmenter()
        if self.wake_stream is not None:
            self.wake_stream.reset()
        notices = [event for event in self.out_queue if event[0] == "notice"]
        self.out_queue.clear()
        self.out_queue.append(("reset", time.monotonic()))
        self.out_queue.extend(notices)
        if self.on_reset:
            self.on_reset()

    def take_event(self):
        with self._lock:
            return self.out_queue.popleft() if self.out_queue else None

    def reset_audio(self):
        """화자가 바뀌면 현재 입력은 유지하고 이전 화자의 발화·화면·판정 상태만 비운다."""
        with self._lock:
            self._reset()

    def stop(self):
        self.running = False
        self._changed.set()

    def _notice(self, key, message):
        with self._lock:
            if key not in self._reported:
                self._reported.add(key)
                self.out_queue.append(("notice", message))
                print(message)

    @property
    def recording(self):
        return self.seg.recording

    def run(self):
        fallback, backoff, refresh = False, MIC_RETRY_S, False
        while self.running:
            with self._lock:
                if self._changed.is_set():
                    fallback, backoff = False, MIC_RETRY_S
                    refresh = True
                    self._changed.clear()
                selection, generation = self._selection, self._generation
            try:
                import sounddevice as sd

                if refresh:
                    # 앱의 유일한 PortAudio 입력을 닫은 뒤 재검색해야 새로 연결된 장치도 보인다.
                    if sd._initialized:
                        sd._terminate()
                    sd._initialize()
                    refresh = False
                mode, requested = selection
                device = (resolve_input_device(sd, None if fallback else requested)
                          if fallback or mode == "endpoint" or requested is None else requested)
                info = sd.query_devices(device, "input")
                extra = (sd.WasapiSettings(auto_convert=True)
                         if sd.query_hostapis(info["hostapi"])["name"] == "Windows WASAPI" else None)
                # __enter__에서 start()가 실패하면 __exit__가 안 불린다 — 그때도 반드시 닫는다.
                with closing(sd.InputStream(samplerate=SR, channels=1, dtype="int16",
                                            blocksize=BLOCK, device=device, extra_settings=extra)) as stream:
                    stream.start()
                    self.device, self.error = device, None
                    last_data = time.monotonic()
                    recovered = False
                    while self.running and not self._changed.is_set():
                        # 쌓인 블록만 읽어야 끊긴 장치의 read()가 설정 변경을 막지 않는다.
                        if not stream.active or time.monotonic() - last_data > MIC_STALL_S:
                            raise OSError("마이크 입력이 중단됐습니다")
                        if stream.read_available < BLOCK:
                            self._changed.wait(BLOCK / SR)
                            continue
                        data, overflowed = stream.read(BLOCK)
                        last_data = time.monotonic()
                        with self._lock:
                            if generation != self._generation:
                                generation = self._generation
                                continue  # 설정 변경이면 루프가 끝나고, 화자 변경이면 같은 입력으로 이어간다.
                            if overflowed:
                                # 끊긴 현재 세그먼트만 버린다 — 완성된 발화·확인 대기·추론은 유효하다.
                                self.seg = VadSegmenter()
                                if self.wake_stream is not None:
                                    self.wake_stream.reset()
                                if last_data - self._last_overflow_log >= MIC_OVERFLOW_LOG_S:
                                    print("[마이크] 입력 오버플로 — 진행 중인 발화만 폐기합니다.")
                                    self._last_overflow_log = last_data
                                continue
                            if not recovered:
                                # 열기 직후 다시 실패하는 장치도 있다 — 정상 블록을 받은 뒤 안내를 재허용한다.
                                self._reported.clear()
                                recovered = True
                            # 시동어를 조각보다 먼저 본다 — 한 블록에서 히트와 조각 종료가 같이 나면 히트가
                            # 먼저 들어가야 assistant 가 그 조각을 "호출어 없음" 으로 버리지 않는다.
                            if self.wake_stream is not None:
                                hit = self.wake_stream.feed(data[:, 0], last_data)
                                if hit is not None:
                                    # 세션 안에서는 자르지 않는다 — 긴 명령 도중 오탐이 나면 명령 앞이 잘린다.
                                    cut = (self.seg.recording and last_data - self.seg.onset_t > WAKE_CUT_S
                                           and (self.cut_ok is None or self.cut_ok(self.seg.onset_t)))
                                    if cut:
                                        self.seg.cut(last_data, WAKE_CUT_S)
                                    self.out_queue.append(hit + (cut,))
                            ev = self.seg.feed(data[:, 0], last_data)
                            if ev is not None:
                                self.out_queue.append(ev)
                        backoff = MIC_RETRY_S
            except Exception as exc:
                with self._lock:
                    if generation != self._generation:
                        continue
                    self.error = exc
                    self._reset()
                if selection[1] is not None and not fallback:
                    fallback = True
                    self._notice("fallback", "선택한 마이크를 사용할 수 없어 시스템 기본 마이크로 전환합니다.")
                    continue
                self._notice("unavailable", "마이크를 사용할 수 없습니다. 장치 연결과 권한을 확인해 주세요. 자동으로 다시 시도합니다.")
                self._changed.wait(backoff)
                backoff = min(backoff * 2, MIC_RETRY_MAX_S)
                fallback = False
                refresh = True
