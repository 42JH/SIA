# -*- coding: utf-8 -*-
"""사용자 지정 호출어 판정 헤드 — 호출어 등록 녹음 5회로 그 자리에서 학습한다.

"시아야"는 그 단어만 따로 학습한 ONNX 모델(models/siaya_v2.onnx)로 듣는다. 사용자가 정한 새 호출어에는
그런 모델이 없으므로, openWakeWord 의 공용 음성 특징(80 ms 마다 96차원)을 그대로 쓰고 최근 16프레임(1.28 s)을
펼친 1536차원 위에 로지스틱 회귀 하나만 학습한다. 정답은 등록 녹음을 변형해 늘린 것, 오답은 미리 모아 둔
한국어 말소리 특징 묶음(부정 뱅크, models/wake_neg_bank.npz)이다. 학습은 녹음 5개·뱅크 2000창에서 특징 추출까지
3초 안팎이다 (개발 PC CPU 실측).

이 헤드는 "그 단어처럼 들린다"까지만 본다. 임계를 낮게 두고, 받아쓰기 모델의 단어 확률 확인과 등록 목소리
확인이 뒤에서 거른다. 임계는 두 개다 — 말하는 도중에 보는 상시 추론과 발화를 통째로 채점할 때의 점수 분포가
달라서다 (HEAD_STREAM_THRESHOLD · HEAD_UTTER_THRESHOLD).

부정 뱅크는 만들어 둔 파일을 함께 올린다 (models/wake_neg_bank.npz — 출처는 NEG_BANK 옆 주석).
자가 검사: python wake_head.py --selftest
"""
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
NEG_BANK = HERE / "models" / "wake_neg_bank.npz"
# 뱅크 2000창의 출처: 낭독 1000창(Zeroth-Korean 700 · FLEURS 한국어 300, 둘 다 CC BY 4.0)과 영상 소리 1000창
# (작업자가 스피커로 틀어 녹음한 한국어 다큐). 팀원 목소리는 넣지 않았다. 들어 있는 것은 1.28 s 창마다 숫자
# 1536개라 원래 소리로 되돌릴 수 없다. 리포를 공개하면 영상 소리 부분을 빼고 다시 만든다.
# 크기 2000창은 1천~1만 창을 견줘 정했다 — 최종 판정이 모두 같았고(본인 호출 37~38/41 통과, 무관한 말 0건),
# 절반을 영상 소리로 채우니 헤드가 영상 소리에 반응하는 횟수가 시간당 80회 → 41회로 줄었다.
SR = 16000
HEAD_FRAMES = 16           # openWakeWord 기본 헤드와 같은 창 길이 (16프레임 = 1.28 s)
HEAD_DIM = 1536            # 16프레임 × 96차원
HEAD_CANVAS = 32000        # 2 s — 이 길이를 특징으로 바꾸면 정확히 16프레임이 나온다
HEAD_AUG = 30              # 등록 녹음 하나를 몇 개로 늘려 학습하는가
HEAD_AUG_LATE_P = 0.3      # NOTE(튜닝): 증강 중 이 비율은 호출어를 캔버스 끝에 붙여 "뒤에 여유가 없는" 창도 정답으로 배운다.
                           # 0 이면 정답이 전부 "호출어 + 뒤따르는 무음" 이라, 조각이 말끝에서 잘릴 때 상시 추론이 놓친다.
                           # 실측(본인 녹음): 말끝에서 자른 조각의 상시 추론 히트 6/20 → 16/20, 라이브 호출 6/13 → 7/8,
                           # 상시 최고점 중앙 0.08 → 0.92, 경계가 틀려 목소리 확인에서 거절되던 호출 5건 → 0건.
                           # 올리면 배경 반응이 는다 (배경만 흘렸을 때 분당 0.96 → 2.06회). 최종 판정 정확도는 바뀌지 않았다.
HEAD_EXTRACTOR = "openwakeword-embedding-16x96"   # 등록 파일·부정 뱅크가 같은 특징으로 만들어졌는지 대조하는 이름
HEAD_STREAM_THRESHOLD = 0.1   # NOTE(튜닝): 상시 추론(HeadStream)이 조각을 살릴지 정하는 값. 말하는 도중 최근 16프레임만 보므로
                       # 같은 호출도 점수가 낮게 나온다 — 실측(본인 호출 13건) 0.114~0.933, 중앙 0.219. 올리면 호출을 통째로 놓친다.
HEAD_UTTER_THRESHOLD = 0.5    # NOTE(튜닝): 발화를 통째로 채점할 때(score_utterance) 쓰는 값. 앞뒤 무음을 붙여 창을 밀며 최고점을 고르므로
                       # 점수가 높게 나온다 — 실측 본인 호출 14건 0.860~1.000. 0.1 → 0.5 로 올려도 14건 모두 통과하고,
                       # 뒤 단계에서 거절될 발화가 14건 중 8건으로 줄어 단어 확률 호출(발화당 약 50 ms)이 그만큼 준다.
                       # 오탐 자체는 이 값으로 못 막는다 — 거절된 14건 중 6건이 0.9 를 넘는다.
HEAD_DEBOUNCE_S = 1.5      # NOTE(튜닝): 같은 호출을 이웃 블록에서 여러 번 잡지 않게 두는 간격 (voice.WAKE_STREAM_DEBOUNCE_S 와 같은 값).


def _features():
    """openWakeWord 공용 특징 추출기. 무거운 import 라 쓸 때 올린다."""
    from openwakeword.utils import AudioFeatures

    return AudioFeatures(inference_framework="onnx")


def _prob(head, z):
    """특징 창(1536차원, 여러 개면 행마다) → 호출어 확률."""
    W, b, mu, sd = head
    x = ((z - mu) / sd) @ W + b
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30.0, 30.0)))   # 아주 먼 창에서 exp 가 넘쳐 경고가 나지 않게 자른다


def _speech(clip_i16):
    """녹음에서 말소리 구간만 남긴다 (앞뒤 0.1 s 여유). 녹음마다 앞뒤 무음 길이가 달라, 그대로 두면
    아래 변형의 위치 조절이 뜻대로 되지 않는다. 구간 = 20 ms 프레임 rms 가 max(하위 10 % × 3, 0.004) 를
    넘는 첫 프레임부터 끝 프레임까지. 그런 프레임이 없으면 녹음 전체를 쓴다."""
    x = np.asarray(clip_i16, dtype=np.float32) / 32768.0
    n = int(0.02 * SR)
    m = len(x) // n
    if m == 0:
        return x
    rms = np.sqrt(np.mean(x[:m * n].reshape(m, n) ** 2, axis=1))
    loud = np.flatnonzero(rms > max(float(np.percentile(rms, 10)) * 3, 0.004))
    if not len(loud):
        return x
    pad = int(0.1 * SR)
    return x[max(0, loud[0] * n - pad):min(len(x), (loud[-1] + 1) * n + pad)]


def _windows(E):
    """임베딩 (프레임 수, 96) → 연속 16프레임 창을 펼친 (창 수, 1536). i번째 창 = E[i:i+16]."""
    windows = np.lib.stride_tricks.sliding_window_view(E, HEAD_FRAMES, axis=0)   # (창 수, 96, 16)
    return windows.transpose(0, 2, 1).reshape(-1, HEAD_DIM)


def _window(af, canvas):
    """2 s 캔버스(−1~1) → 마지막 16프레임을 펼친 1536차원."""
    e = af._get_embeddings((canvas * 32767).astype(np.int16))
    return e[-HEAD_FRAMES:].reshape(-1).astype(np.float32)


def train_head(clips_i16, bank_X, feats=None):
    """등록 녹음들(int16) + 부정 뱅크 → 헤드 (W, b, mu, sd), 모두 float32.

    녹음마다 HEAD_AUG 개로 늘린다. 첫 개는 원본을 2 s 캔버스의 0.4 s 위치에 두고, 나머지는 속도(피치도 함께 변한다)·
    크기·위치를 바꾼다. 위치를 바꾸는 이유: 실행 중에는 16프레임 창이 80 ms 씩 밀리므로 호출어가 창 안 어디서
    끝나도 잡혀야 한다. 그중 HEAD_AUG_LATE_P 는 호출어를 캔버스 끝에 붙인다 — 뒤에 무음이 남는 창만 정답으로
    배우면 말끝에서 잘린 조각을 상시 추론이 놓친다. 잡음은 섞지 않는다 — 앱에는 섞을 잡음 녹음이 없고, 빼도 실측 결과가 같았다.
    정답이 150개 안팎이라 오답(뱅크 수천 개)과 무게를 class_weight="balanced" 로 맞춘다."""
    from scipy.signal import resample_poly
    from sklearn.linear_model import LogisticRegression

    af = feats or _features()
    rng = np.random.default_rng(0)   # 같은 녹음이면 같은 헤드가 나오게 고정한다
    pos = []
    for clip in clips_i16:
        seg = _speech(clip)
        for k in range(HEAD_AUG):
            s, offset = seg, 0.4
            if k:
                speed = rng.choice([0.9, 1.0, 1.1])
                if speed != 1.0:
                    s = resample_poly(s, 10, round(10 * speed))
                s = s * 10 ** (rng.uniform(-6, 6) / 20)
                if rng.random() < HEAD_AUG_LATE_P:
                    hi = max(0.2, HEAD_CANVAS / SR - len(s) / SR)   # 잘리지 않고 가장 늦게 놓을 수 있는 자리
                    offset = rng.uniform(max(0.2, hi - 0.15), hi)
                else:
                    offset = rng.uniform(0.2, 0.8)
            canvas = np.zeros(HEAD_CANVAS, dtype=np.float32)
            o = int(offset * SR)
            s = s[:HEAD_CANVAS - o]
            canvas[o:o + len(s)] = s
            pos.append(_window(af, np.clip(canvas, -1, 1)))
    neg = np.asarray(bank_X, dtype=np.float32)
    X = np.concatenate([np.stack(pos), neg])
    y = np.concatenate([np.ones(len(pos)), np.zeros(len(neg))])
    mu = X.mean(axis=0)
    sd = X.std(axis=0) + 1e-6
    clf = LogisticRegression(C=0.5, class_weight="balanced", max_iter=3000)
    clf.fit((X - mu) / sd, y)
    return (clf.coef_[0].astype(np.float32), np.float32(clf.intercept_[0]),
            mu.astype(np.float32), sd.astype(np.float32))


def load_bank(path=NEG_BANK):
    """부정 뱅크 X (n, 1536) float16 을 읽는다. 다른 특징으로 만들었거나 깨진 파일은 ValueError,
    파일이 없으면 FileNotFoundError 를 그대로 올린다."""
    import zipfile

    try:
        with np.load(path, allow_pickle=False) as data:
            X, extractor = data["X"], str(data["extractor"])
    except (KeyError, TypeError, EOFError, zipfile.BadZipFile) as e:   # TypeError = npz 가 아닌 .npy
        raise ValueError(f"부정 뱅크를 읽을 수 없습니다: {e!r}") from e
    if extractor != HEAD_EXTRACTOR:
        raise ValueError(f"다른 특징으로 만든 부정 뱅크입니다 ({extractor})")
    if (X.ndim != 2 or X.shape[0] < 1000 or X.shape[1] != HEAD_DIM
            or X.dtype.kind != "f" or not np.isfinite(X).all()):
        raise ValueError(f"부정 뱅크는 1000개 이상의 유한한 {HEAD_DIM}차원 행이어야 합니다 {X.shape}")
    return X


def score_utterance(feats, head, audio_i16, threshold=HEAD_UTTER_THRESHOLD):
    """발화 통째 채점 → (최고 점수, 최고점 창의 끝 시각 s 또는 None).

    앞뒤에 무음 1 s 를 붙인다 — 짧은 발화도 16프레임 창을 채우고, 발화 맨 끝에서 끝나는 창까지 채점된다.
    끝 시각은 발화 기준 초다 (붙인 1 s 를 뺀 값).

    끝 시각을 처음 임계를 넘은 창이 아니라 최고점 창에서 잡는다. 멜 변환이 클립 최대값에서 80 dB 아래를
    바닥으로 자르므로, 큰 호출어 앞에 붙은 조용한 배경은 프레임 70 % 가 바닥에 눌려 학습 캔버스의 무음
    패딩처럼 보이고, 말소리가 없는 창에서도 점수가 0.69 까지 나온다. 그래서 첫 넘음은 실제 호출어보다
    중앙 0.8~1.1 s (최대 3.6 s) 일찍 찍힌다. 프리롤을 붙인 실측(호출어 2개 56건): 단어 확률 통과
    30/56 → 55/56, 경계 붕괴 19건 → 0건, 화자 유사도 최저 0.310 → 0.389, 부정 620건 오통과는 0 그대로.
    NOTE(한계): 대신 경계가 늦어져 뒤에 붙은 명령을 삼킬 수 있다 — brain 이 단독 호출 판정에 말소리 길이
    (WAKE_SOLO_MAX_SPEECH_S)를 같이 본다."""
    pad = np.zeros(SR, dtype=np.int16)
    E = feats._get_embeddings(np.concatenate([pad, np.asarray(audio_i16, dtype=np.int16), pad]))
    if len(E) < HEAD_FRAMES:
        return 0.0, None
    p = _prob(head, _windows(E))
    i = int(np.argmax(p))
    if p[i] < threshold:
        return float(p[i]), None
    k = i + HEAD_FRAMES - 1   # 그 창의 마지막 임베딩 번호
    # k번째 임베딩은 멜 76프레임(0.76 s)을 보는 첫 임베딩에서 80 ms 씩 밀린 지점에서 끝난다
    return float(p[i]), (76 * 160 + 1280 * k) / SR - 1.0


class HeadStream:
    """voice.WakeStream 과 같은 모양 — 마이크 블록을 흘려 사용자 지정 호출어를 말하는 도중에 잡는다.

    특징 추출기를 스트림마다 따로 만든다. 안에 앞 문맥(멜·임베딩 버퍼)이 있어, 다른 인스턴스와 나눠 쓰면
    서로의 문맥을 망친다. 블록마다 최근 16프레임을 채점하고, 새 임베딩은 80 ms 마다 생기므로 그 사이
    블록은 같은 점수를 다시 낸다."""

    def __init__(self, head, threshold=HEAD_STREAM_THRESHOLD):
        self.head = head
        self.threshold = threshold
        self.threshold_lo = threshold   # 헤드에는 낮은 임계의 민감 상태가 없다 — WakeStream 과 속성만 맞춘다
        self.af = _features()
        self._warm()

    def _warm(self):
        """무음 2 s 를 먼저 흘린다 (점수·히트는 버린다). openWakeWord 는 만들 때와 reset 때 특징 버퍼를
        무작위 잡음으로 채워, 그대로 들으면 약 1.3 s 안에 헛히트가 난다. 유튜브 배경 녹음을 파일마다 새로
        들었을 때 앞 2 s 의 헛히트가 19건이었고, 무음 2 s 를 먼저 흘리면 7건으로 줄었다 (그 뒤 히트 수는 같았다).
        무음 2 s 는 특징 25프레임이라 창 16프레임이 모두 무음으로 바뀐다."""
        self.af(np.zeros(2 * SR, dtype=np.int16))
        self.last_score = 0.0
        self._last_hit = float("-inf")

    def feed(self, block_i16, t):
        """블록 하나 투입. 반환: None | ("wake_live", t, score)."""
        self.af(block_i16)
        z = np.asarray(self.af.get_features(HEAD_FRAMES)).reshape(-1)
        score = float(_prob(self.head, z)) if z.size == HEAD_DIM else 0.0
        self.last_score = score
        if score >= self.threshold and t - self._last_hit >= HEAD_DEBOUNCE_S:
            self._last_hit = t
            return ("wake_live", t, round(score, 3))
        return None

    def reset(self):
        """장치 전환·오버플로로 오디오가 끊기면 추출기 안에 남은 앞 문맥을 버린다."""
        self.af.reset()
        self._warm()


def _synthetic(af):
    """자가 검사용 합성 데이터 — 주파수가 서로 다른 사인파 '호출어' 5개(앞뒤 무음 0.3 s)와 무작위 부정 뱅크 2000개.
    뱅크는 2 s 마다 크기가 무작위(사실상 무음 ~ 큰 소리)인 백색 잡음의 실제 특징 창이다. 정규분포 난수를 그대로
    뱅크로 쓰면 헤드가 "실제 특징처럼 생겼나"만 배워 무음까지 호출어로 판정한다."""
    rng = np.random.default_rng(1)
    t = np.arange(int(0.6 * SR)) / SR
    gap = np.zeros(int(0.3 * SR), dtype=np.int16)
    clips = [np.concatenate([gap, (np.sin(2 * np.pi * f * t) * 8000).astype(np.int16), gap])
             for f in (300, 500, 700, 900, 1100)]
    noise = np.concatenate([rng.standard_normal(2 * SR) * a for a in 10 ** rng.uniform(-1, 4, 90)])
    bank = _windows(af._get_embeddings(np.clip(noise, -32768, 32767).astype(np.int16)))[:2000]
    return clips, bank.astype(np.float16)


def _selftest():
    import io

    af = _features()
    clips, bank = _synthetic(af)
    head = train_head(clips, bank, af)
    assert all(v.dtype == np.float32 for v in head), "헤드 값은 모두 float32 여야 함"
    for clip in clips:
        top, end = score_utterance(af, head, clip)
        assert top > 0.5 and end is not None, f"학습한 녹음이 잡혀야 함: {top}"
    top, end = score_utterance(af, head, np.zeros(2 * SR, np.int16))
    assert top < 0.1 and end is None, f"무음은 잡히면 안 됨: {top}"

    # 상시 추론은 말끝에서 잘린 조각(뒤에 무음이 남지 않는 창)도 잡아야 한다 — 늦은 배치 증강이 맡는 몫이다.
    # score_utterance 는 앞뒤에 무음 1 s 를 붙여 채점하므로 이 회귀를 보지 못한다.
    stream = HeadStream(head)
    block = 480
    for clip in clips:
        cut = clip[:len(clip) - int(0.3 * SR)]   # 뒤 무음을 잘라낸 조각
        stream.reset()
        hits = [stream.feed(cut[i:i + block], i / SR) for i in range(0, len(cut) - block + 1, block)]
        assert any(hits), f"말끝에서 잘린 조각을 상시 추론이 잡아야 함: {stream.last_score}"
    stream.reset()
    silence = np.zeros(3 * SR, np.int16)
    quiet = [stream.feed(silence[i:i + block], i / SR) for i in range(0, len(silence) - block + 1, block)]
    assert not any(quiet), f"무음에는 상시 추론 히트가 없어야 함: {stream.last_score}"

    def npz(**fields):
        buf = io.BytesIO()
        np.savez(buf, **fields)
        buf.seek(0)
        return buf

    assert load_bank(npz(X=bank, extractor=HEAD_EXTRACTOR)).shape == (2000, HEAD_DIM)
    for broken in (io.BytesIO(b"not an npz"), io.BytesIO(b""), npz(X=bank),
                   npz(X=bank, extractor="other"), npz(X=bank[:10], extractor=HEAD_EXTRACTOR),
                   npz(X=bank[:, :96], extractor=HEAD_EXTRACTOR)):
        try:
            load_bank(broken)
        except ValueError:
            continue
        raise AssertionError("깨진 부정 뱅크를 받아들임")
    try:
        load_bank(HERE / "models" / "없는_파일.npz")
        raise AssertionError("없는 파일은 FileNotFoundError 여야 함")
    except FileNotFoundError:
        pass
    print("selftest ok")


if __name__ == "__main__":
    import sys

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # cp949 콘솔에서 한글 출력 크래시 방지
    except Exception:
        pass
    if "--selftest" in sys.argv:
        _selftest()
