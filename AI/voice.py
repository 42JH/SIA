# -*- coding: utf-8 -*-
"""상시 음성 대기.

에너지 기반 VAD(적응 노이즈 임계)로 발화를 잘라낸다. STT는 여기서 하지 않는다 —
오디오 원본을 Gemini에 화면과 함께 그대로 보내는 융합 콜 구조이므로,
이 모듈의 책임은 "언제부터 언제까지가 발화인가"와 **발화 시작 시각**뿐이다.
(시작 시각이 중요한 이유: 그 순간의 응시 위치를 링버퍼에서 조회해야 하므로.)

이벤트 큐로 내보내는 것:
  ("onset", t)          — 발화 시작 감지 (이 순간 화면·응시를 캡처할 것)
  ("utter", t, audio)   — 발화 종료, int16 mono 오디오 전체
"""
import threading
import time

import numpy as np

SR = 16000
BLOCK = 480  # 30ms


class VadSegmenter:
    """블록 단위 RMS로 발화 구간을 자르는 순수 로직 (테스트 가능).

    NOTE(한계): 에너지 VAD — 조용한 실내 기준. 시끄러운 환경이 문제 되면
    webrtcvad/실크 VAD로 교체할 것.
    """

    def __init__(self, sr=SR, block=BLOCK, start_blocks=3, end_silence_s=0.55,
                 preroll_s=0.7, max_s=12.0, min_speech_s=0.35, floor=350.0,
                 noise_win_s=40.0, noise_pct=80.0, ratio=1.5):
        # start 3블록(90ms)+프리롤 0.7초 — 호출어 첫 음절이 잘리면 명령 전체가 기각되므로 시작은 후하게 잡는다.
        # (2 → 3 블록: 유튜브 오탐 −30% 에 검출 −0~1 — 가장 싼 레버)
        # 노이즈 바닥 = 최근 noise_win_s 초 블록 rms 의 noise_pct 백분위, **녹음 중에도** 매 블록 갱신.
        # 유튜브처럼 임계를 넘는 배경이 계속되면 옛 방식(임계 아래·비녹음 블록에서만 EMA)은 바닥이 얼어붙어
        # 12초 상한 덩어리를 연달아 자르고 호출을 그 안에 삼킨다. 최솟값·하위 분위는 말소리 사이 틈을 재서 소용없다.
        # 창 40 s: 본인 말이 창의 20% 를 못 채워야 바닥이 본인 레벨로 안 뜬다 (20 s 는 4 s 발화 뒤 후속 호출을 놓쳤다).
        # 조용한 곳에선 바닥×ratio < floor 라 임계 = floor 350, 옛 동작과 같다. noise_win_s=0 이면 옛 EMA (비교용).
        self.block_dur = block / sr
        self.ratio = ratio
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
        self.recording = False
        self._preroll = []
        self._buf = []
        self._hot = 0
        self._quiet = 0
        self._speech = 0
        self._onset_t = 0.0

    @property
    def threshold(self):
        return max(self.noise * self.ratio, self.floor)

    def feed(self, block_i16, t):
        """블록 하나 투입. 반환: None | ("onset", t) | ("utter", t_onset, audio)."""
        rms = float(np.sqrt(np.mean(block_i16.astype(np.float32) ** 2)))
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
                self._onset_t = t - self.start_blocks * self.block_dur
                return ("onset", self._onset_t)
            return None
        # 녹음 중
        self._buf.append(block_i16)
        if rms > self.threshold:
            self._quiet = 0
            self._speech += 1
        else:
            self._quiet += 1
        if self._quiet >= self.end_blocks or len(self._buf) >= self.max_blocks:
            self.recording = False
            buf, self._buf = self._buf, []
            if self._speech >= self.min_speech_blocks:
                return ("utter", self._onset_t, np.concatenate(buf))
            return None  # 너무 짧음 (기침, 소음) — 버림
        return None


class VoiceListener(threading.Thread):
    """마이크 전용 스레드 — VadSegmenter 이벤트를 out_queue로 흘린다."""

    def __init__(self, out_queue, device=None):
        super().__init__(daemon=True)
        self.out_queue = out_queue
        self.device = device
        self.seg = VadSegmenter()
        self.running = True
        self.error = None

    @property
    def recording(self):
        return self.seg.recording

    def run(self):
        try:
            import sounddevice as sd

            with sd.InputStream(samplerate=SR, channels=1, dtype="int16",
                                blocksize=BLOCK, device=self.device) as stream:
                while self.running:
                    data, _ = stream.read(BLOCK)
                    ev = self.seg.feed(data[:, 0], time.monotonic())
                    if ev is not None:
                        self.out_queue.append(ev)
        except Exception as e:  # 마이크 없음/점유 등 — 비서는 제스처만으로 계속 동작
            self.error = e
            print(f"음성 대기 중단: {e}")
