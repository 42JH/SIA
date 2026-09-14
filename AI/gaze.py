# -*- coding: utf-8 -*-
"""시선 추정 파이프라인.

FaceLandmarker → 홍채/머리자세 특징 벡터 → (개인 캘리브레이션 회귀) → 화면 px 좌표.
좌표는 GazeBuffer(링버퍼)에만 쌓인다. 커서는 여기서 절대 건드리지 않는다 —
시선은 트리거 순간에만 소비되는 read-only 신호 (Midas touch 방지의 핵심).
"""
import collections
import math
import os
import threading
import time

import numpy as np


def _atomic_savez(path, **arrays):
    """임시 파일에 쓰고 os.replace — 쓰는 도중 죽어도 기존 파일이 깨지지 않는다."""
    path = str(path)
    tmp = path + ".tmp.npz"  # np.savez는 .npz로 안 끝나면 확장자를 덧붙이므로 명시
    np.savez(tmp, **arrays)
    os.replace(tmp, path)

# FaceMesh(478) 랜드마크 인덱스
R_IRIS, L_IRIS = 468, 473
R_IN, R_OUT, R_TOP, R_BOT = 133, 33, 159, 145
L_IN, L_OUT, L_TOP, L_BOT = 362, 263, 386, 374

FEATURE_DIM = 12  # 눈 6 + 머리자세 6


def _clamp1(v):
    return max(-1.0, min(1.0, v))


def gaze_features(result):
    """FaceLandmarkerResult → (12,) 특징 벡터. 얼굴 없으면 None."""
    if not result.face_landmarks:
        return None
    lm = result.face_landmarks[0]

    def p(i):
        return np.array([lm[i].x, lm[i].y])

    feats = []
    for iris, cin, cout, top, bot in (
        (R_IRIS, R_IN, R_OUT, R_TOP, R_BOT),
        (L_IRIS, L_IN, L_OUT, L_TOP, L_BOT),
    ):
        w = float(np.linalg.norm(p(cout) - p(cin))) + 1e-6
        center = (p(cout) + p(cin)) / 2.0
        off = (p(iris) - center) / w          # 홍채 오프셋 (눈 크기 정규화)
        feats += [off[0], off[1]]
        feats.append(float(np.linalg.norm(p(top) - p(bot))) / w)  # 눈 개폐 (상하 시선 보조)

    if result.facial_transformation_matrixes is not None and len(result.facial_transformation_matrixes):
        m = np.asarray(result.facial_transformation_matrixes[0], dtype=float)
        yaw = math.atan2(m[0, 2], m[2, 2])
        pitch = math.asin(_clamp1(-m[1, 2]))
        roll = math.atan2(m[1, 0], m[1, 1])
        feats += [yaw, pitch, roll, m[0, 3] / 100.0, m[1, 3] / 100.0, m[2, 3] / 100.0]
    else:
        feats += [0.0] * 6
    return np.array(feats)


class Calibrator:
    """2차 다항 ridge 회귀: 특징(12) → 화면 좌표(정규화 0~1).

    닫힌 형태 해라 sklearn 불필요. 화면 크기는 저장해뒀다가 predict에서 px로 복원.
    """

    def __init__(self, screen_w, screen_h, lam=1e-3):
        self.screen = (int(screen_w), int(screen_h))
        self.lam = lam
        self.W = None   # (poly_dim, 2)
        self.X0 = None  # 기본 캘리브레이션 샘플 — 클릭 재보정 때 합산용
        self.Y0 = None

    @staticmethod
    def _expand(X):
        X = np.atleast_2d(np.asarray(X, dtype=float))
        n, d = X.shape
        cross = [X[:, i] * X[:, j] for i in range(d) for j in range(i, d)]
        return np.hstack([np.ones((n, 1)), X, np.stack(cross, axis=1)])

    def fit(self, feats, targets_px, weights=None):
        """feats (n,12), targets_px (n,2). 비가중 RMS 오차(px) 반환."""
        A = self._expand(feats)
        Y = np.asarray(targets_px, dtype=float) / np.array(self.screen)
        Aw, Yw = A, Y
        if weights is not None:
            r = np.sqrt(np.asarray(weights, dtype=float))[:, None]
            Aw, Yw = A * r, Y * r
        reg = self.lam * np.eye(A.shape[1])
        self.W = np.linalg.solve(Aw.T @ Aw + reg, Aw.T @ Yw)
        err = (A @ self.W - Y) * np.array(self.screen)
        return float(np.sqrt((err ** 2).sum(axis=1).mean()))

    LAM_GRID = (1e-3, 3e-3, 1e-2, 3e-2, 1e-1)

    def fit_base(self, feats, targets_px):
        """최초 캘리브레이션: λ를 교차검증으로 선택 후 학습. 샘플은 보관(클릭 재보정용).

        고정 λ는 특징 차원이 늘면 과적합한다(학습 잔차↓ 검증 오차↑). 캘리브레이션
        점 하나씩 통째로 빼는 leave-one-point-out으로 '안 본 지점' 오차를 직접
        최소화하는 λ를 고른다. 반환값은 그 교차검증 평균 오차(px) — 학습 잔차보다
        정직한 성능 추정치.
        """
        self.X0 = np.asarray(feats, dtype=float)
        self.Y0 = np.asarray(targets_px, dtype=float)
        A = self._expand(self.X0)
        scr = np.array(self.screen)
        Yn = self.Y0 / scr
        _, labels = np.unique(self.Y0, axis=0, return_inverse=True)
        if labels.max() + 1 > 30:  # 점 단위 그룹이 없으면(연속 좌표) 5-fold로
            labels = np.arange(len(self.Y0)) % 5
        eye = np.eye(A.shape[1])
        best_err, best_lam = np.inf, self.lam
        for lam in self.LAM_GRID:
            errs = []
            for g in np.unique(labels):
                tr = labels != g
                W = np.linalg.solve(A[tr].T @ A[tr] + lam * eye, A[tr].T @ Yn[tr])
                e = (A[~tr] @ W - Yn[~tr]) * scr
                errs.append(np.sqrt((e ** 2).sum(axis=1)))
            err = float(np.concatenate(errs).mean())
            if err < best_err:
                best_err, best_lam = err, lam
        self.lam = best_lam  # 저장돼서 이후 클릭 재보정도 같은 λ 사용
        self.fit(self.X0, self.Y0)
        return best_err

    def refit_with_clicks(self, click_feats, click_px, weight=3.0):
        """기본 샘플 + 클릭 샘플(가중치 weight)로 재학습. RMS(px) 반환.
        기본 샘플이 없으면(구형 calib) ValueError."""
        if self.X0 is None or not len(self.X0):
            raise ValueError("기본 캘리브레이션 샘플 없음 — calibrate.py를 다시 실행하세요")
        cX = np.atleast_2d(np.asarray(click_feats, dtype=float))
        cY = np.atleast_2d(np.asarray(click_px, dtype=float))
        X = np.vstack([self.X0, cX])
        Y = np.vstack([self.Y0, cY])
        w = np.concatenate([np.ones(len(self.X0)), np.full(len(cX), weight)])
        return self.fit(X, Y, weights=w)

    def predict(self, feat):
        """특징 1개 → 화면 px. 모서리에서 2px 안쪽으로 clamp —
        정확히 (0,0) 등 네 모서리는 pyautogui failsafe를 자폭시키기 때문."""
        xy = (self._expand(feat)[0] @ self.W) * np.array(self.screen)
        return (
            float(np.clip(xy[0], 2, self.screen[0] - 3)),
            float(np.clip(xy[1], 2, self.screen[1] - 3)),
        )

    def save(self, path):
        _atomic_savez(path, W=self.W, screen=np.array(self.screen), lam=self.lam,
                      X0=self.X0 if self.X0 is not None else np.zeros((0, FEATURE_DIM)),
                      Y0=self.Y0 if self.Y0 is not None else np.zeros((0, 2)))

    @classmethod
    def load(cls, path):
        d = np.load(path)
        c = cls(d["screen"][0], d["screen"][1], float(d["lam"]))
        c.W = d["W"]
        if "X0" in d.files and len(d["X0"]):
            c.X0, c.Y0 = d["X0"], d["Y0"]
        return c


class ClickRecal:
    """클릭 기반 상시 재보정 — 실물 클릭 순간의 (시선 특징, 클릭 좌표)는 공짜
    정답 라벨이다. refit_every개 모일 때마다 기본 캘리브레이션과 합쳐 재학습하고
    디스크에 저장한다(다음 실행에도 유지). 데모가 만든 합성 클릭을 걸러내는 것은
    호출자 책임 — 안 거르면 자기 예측을 정답으로 배우는 피드백 루프가 된다.
    add()는 무거운 작업(재학습·파일쓰기)을 하므로 반드시 메인 루프에서 호출할 것
    — 전역 마우스 훅 콜백 안에서 돌리면 시스템 전체 커서가 멈추고 훅이 제거된다.
    """

    def __init__(self, calib, calib_path, clicks_path,
                 refit_every=5, weight=3.0, max_samples=200, gate_px=500.0):
        self.calib = calib
        self.calib_path = calib_path
        self.clicks_path = clicks_path
        self.refit_every = refit_every
        self.weight = weight
        # max_samples×weight ≈ 기본 샘플 총량 — 클릭이 기본 캘리브레이션을 압도하지 않게
        self.max_samples = max_samples
        self.gate_px = gate_px
        self.X, self.Y = [], []
        try:
            d = np.load(clicks_path)
            # 해상도·특징 차원이 바뀌었으면 옛 클릭 샘플은 무효 → 버린다
            if ("screen" in d.files and tuple(d["screen"]) == tuple(calib.screen)
                    and (calib.X0 is None or d["X"].shape[1] == calib.X0.shape[1])):
                self.X = [row for row in d["X"]]
                self.Y = [row for row in d["Y"]]
        except Exception:
            pass  # 클릭 캐시는 소모품 — 깨진 파일 때문에 죽지 않는다 (다음 저장 때 덮어씀)
        self._pending = 0

    def add(self, feat, x, y):
        """샘플 추가. 재학습이 일어나면 RMS(px) 반환, 아니면 None.

        정합성 게이트: 현재 예측과 gate_px 이상 어긋난 클릭은 '보면서 클릭했다'는
        가정 위반(딴 데 보며 클릭)일 확률이 높아 버린다 — 오답 라벨이 쌓이면
        지도가 통째로 밀리는 자기강화 드리프트가 생긴다.
        """
        px, py = self.calib.predict(feat)
        if math.hypot(px - float(x), py - float(y)) > self.gate_px:
            return None
        self.X.append(np.asarray(feat, dtype=float))
        self.Y.append(np.array([float(x), float(y)]))
        self.X = self.X[-self.max_samples:]
        self.Y = self.Y[-self.max_samples:]
        self._pending += 1
        if self._pending < self.refit_every:
            return None
        self._pending = 0
        rms = self.calib.refit_with_clicks(np.array(self.X), np.array(self.Y), self.weight)
        self.calib.save(self.calib_path)
        _atomic_savez(self.clicks_path, X=np.array(self.X), Y=np.array(self.Y),
                      screen=np.array(self.calib.screen))
        return rms


class GazeBuffer:
    """(t, x, y) 링버퍼 + dispersion 기반 fixation 검출.

    트리거(핀치/발화)는 '지금 시선'이 아니라 '트리거 직전 fixation'을 조회한다 —
    사람 눈은 행동이 끝나기 전에 다음 대상으로 떠나기 때문 (lookback의 이유).
    """

    def __init__(self, horizon=3.0):
        self.horizon = horizon
        self.samples = collections.deque()
        self._lock = threading.Lock()  # push는 시선 스레드, 조회는 메인 스레드

    def push(self, t, x, y):
        with self._lock:
            self.samples.append((t, x, y))
            while self.samples and t - self.samples[0][0] > self.horizon:
                self.samples.popleft()

    def fixation_at(self, t_query, lookback=0.25, window=0.35, max_disp=90.0):
        """t_query-lookback 근처 fixation 중심. → ((x,y), is_fixation) / 샘플 없으면 (None, False)"""
        t_end = t_query - lookback
        with self._lock:
            pts = [(x, y) for (t, x, y) in self.samples if t_end - window <= t <= t_end]
            if len(pts) < 3:
                # 폴백: 최근 샘플들 — 단 1초 이내 것만. 얼굴 추적이 끊기면 push가 멈춰
                # 오래된 샘플이 버퍼에 남는데, 그걸 신선한 시선인 양 쓰면 안 된다.
                pts = [(x, y) for (t, x, y) in list(self.samples)[-5:] if t_query - t < 1.0]
        if not pts:
            return None, False
        arr = np.array(pts)
        center = np.median(arr, axis=0)
        disp = float(np.abs(arr - center).max())
        # 샘플 1~2개는 분산이 0에 가까워 '확정 응시'를 사칭할 수 있다 → 3개 이상만 인정
        return (float(center[0]), float(center[1])), len(pts) >= 3 and disp < max_disp

    def current(self, t):
        """오버레이 표시용 현재 응시점 (짧은 창 평균)."""
        pt, _ = self.fixation_at(t, lookback=0.0, window=0.25)
        return pt


class FaceEngine:
    """FaceLandmarker(VIDEO 모드) 래퍼. frame(BGR, 이미 미러링됨) → 특징 벡터.

    deep(DeepGaze)을 주면 CNN 시선 각도 2개를 특징에 추가한다 (12 → 14차원).
    특징 차원이 바뀌므로 deep을 켜고 끄면 재캘리브레이션이 필요하다.
    """

    def __init__(self, model_path, deep=None):
        self.deep = deep
        self.dim = FEATURE_DIM + (2 if deep else 0)
        self._init_landmarker(model_path)

    def _init_landmarker(self, model_path):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import (
            FaceLandmarker,
            FaceLandmarkerOptions,
            RunningMode,
        )

        self._mp = mp
        # 경로 대신 바이트로 로드 — 네이티브 라이브러리가 한글 경로를 못 열기 때문
        model_buf = open(model_path, "rb").read()
        self.landmarker = FaceLandmarker.create_from_options(
            FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_buffer=model_buf),
                running_mode=RunningMode.VIDEO,
                num_faces=1,
                output_facial_transformation_matrixes=True,
            )
        )
        self._last_ts = 0
        self.last_ipd_norm = None  # 두 홍채 사이 정규화 거리 — 위치 프리체크(거리) 용, 얼굴 없으면 None
        # detect_for_video는 스레드 안전하지 않고 _last_ts 단조 상태를 공유한다.
        # 재보정 중엔 GazeWorker 스레드와 CalibSession(메인 루프)이 같은 엔진을 동시에 부르는데,
        # 락이 없으면 두 스레드가 같은 _last_ts 를 읽어 같은/역전 ts 를 넣어 "타임스탬프가 증가하지 않음"으로 터진다.
        self._infer_lock = threading.Lock()

    def features(self, frame_bgr, ts_ms=None):
        import cv2

        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        try:
            with self._infer_lock:  # ts 갱신 + MediaPipe 호출을 원자적으로 (스레드 직렬화)
                if ts_ms is None:
                    ts_ms = int(time.monotonic() * 1000)
                ts_ms = max(ts_ms, self._last_ts + 1)  # detect_for_video는 단조증가 필수
                self._last_ts = ts_ms
                result = self.landmarker.detect_for_video(img, ts_ms)
        except Exception as e:  # MediaPipe 간헐 실패 — 한 프레임만 버리고 앱은 계속
            print(f"[시선 추론 오류, 프레임 건너뜀] {type(e).__name__}: {str(e)[:80]}")
            self.last_ipd_norm = None
            return None
        f = gaze_features(result)
        if result.face_landmarks:  # 위치 프리체크(거리)용 홍채간 정규화 거리 갱신
            lm = result.face_landmarks[0]
            self.last_ipd_norm = float(((lm[R_IRIS].x - lm[L_IRIS].x) ** 2
                                        + (lm[R_IRIS].y - lm[L_IRIS].y) ** 2) ** 0.5)
        else:
            self.last_ipd_norm = None
        if f is None or self.deep is None:
            return f
        from deepgaze import face_crop

        pitch, yaw = self.deep.gaze(face_crop(frame_bgr, result.face_landmarks[0]))
        return np.concatenate([f, [pitch, yaw]])


def make_engine(models_dir):
    """torch + ETH-XGaze 가중치가 있으면 CNN 결합 엔진, 없으면 기하 전용 자동 폴백."""
    from pathlib import Path

    import os

    models_dir = Path(models_dir)
    deep = None
    weights = models_dir / "eth-xgaze_resnet18.pth"
    if os.environ.get("NO_DEEP"):  # A/B 비교용: 기하 방식 강제
        print("NO_DEEP 설정 → 기하 방식으로 진행")
    elif weights.exists():
        try:
            from deepgaze import DeepGaze

            deep = DeepGaze(weights)
            print(f"딥 시선 모델 켜짐 (ETH-XGaze ResNet-18, {deep.dev})")
        except Exception as e:
            print(f"딥 시선 모델 비활성({type(e).__name__}: {e}) → 기하 방식으로 진행")
    return FaceEngine(models_dir / "face_landmarker.task", deep=deep)
