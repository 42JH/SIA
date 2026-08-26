# -*- coding: utf-8 -*-
"""손 제스처 파이프라인.

GestureRecognizer(내장 제스처 분류 포함) 래퍼 + 상태머신들.
- 핀치: 랜드마크 거리 기반, 히스테리시스로 떨림 방지
- 손바닥 홀드: Active/Passive 클러치 토글
"""
import collections
import math
import time

import numpy as np

PINCH_ON, PINCH_OFF = 0.35, 0.45  # (엄지-검지 거리 / 손 크기) 히스테리시스


class OneEuro:
    """One Euro 필터 — 포인터 필터의 표준. 정지 시 떨림 억제, 이동 시 지연 최소.

    고정 EMA는 '부드러움 ↔ 지연'을 하나의 상수로 타협하지만, One Euro는 속도에
    따라 컷오프를 올려 빠른 손 이동엔 즉각 반응한다. (Casiez et al. 2012)
    """

    def __init__(self, min_cutoff=1.0, beta=20.0, d_cutoff=1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.reset()

    def reset(self):
        self._t = self._x = self._dx = None

    @staticmethod
    def _alpha(dt, cutoff):
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def __call__(self, x, t):
        x = np.asarray(x, dtype=float)
        if self._t is None:
            self._t, self._x, self._dx = t, x, np.zeros_like(x)
            return x
        dt = max(t - self._t, 1e-3)
        self._t = t
        dx = (x - self._x) / dt
        a_d = self._alpha(dt, self.d_cutoff)
        self._dx = a_d * dx + (1 - a_d) * self._dx
        cutoff = self.min_cutoff + self.beta * float(np.linalg.norm(self._dx))
        a = self._alpha(dt, cutoff)
        self._x = a * x + (1 - a) * self._x
        return self._x


def _dist(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def parse_hand(result):
    """GestureRecognizerResult → dict(anchor, pinch_ratio, gesture) / 손 없으면 None.

    anchor는 중지 MCP(9): 핀치 중에도 안정적으로 움직임을 대표하는 지점.
    """
    if not result.hand_landmarks:
        return None
    lm = result.hand_landmarks[0]
    size = _dist(lm[0], lm[9]) + 1e-6
    gesture = "None"
    if result.gestures and result.gestures[0]:
        gesture = result.gestures[0][0].category_name
    return {
        "anchor": (lm[9].x, lm[9].y),
        "pinch_ratio": _dist(lm[4], lm[8]) / size,
        "gesture": gesture,
        "landmarks": [(p.x, p.y) for p in lm],  # HUD 디버그 표시용
    }


class PinchFSM:
    """핀치 이벤트. update() → 'down' | 'up' | 'lost' | None, .held 로 상태 조회.

    - 무장(arming): 손이 나타난 뒤 벌린 상태(> PINCH_OFF)를 한 번 봐야 'down' 가능
      — 이미 오므린 채 화면에 들어온 손이 즉시 클릭을 만드는 것 방지.
    - 해제 유예: held 중 랜드마크 스파이크/한 프레임 검출 끊김으로 up·down이
      널뛰지 않게, 벌림/소실이 grace_s 연속돼야 해제 확정.
    - 'up' = 실제로 벌려서 놓음(클릭 후보), 'lost' = 손 소실 강제 해제(클릭 금지).
    """

    def __init__(self, release_grace_s=0.12):
        self.release_grace_s = release_grace_s
        self.held = False
        self._armed = False
        self._bad_since = None
        self._bad_kind = None

    def reset(self):
        """즉시 무해제 상태로 — 비활성화 등 외부 사유. 이벤트는 내지 않는다."""
        self.held = False
        self._armed = False
        self._bad_since = None

    def update(self, ratio, t=None):
        t = time.monotonic() if t is None else t
        if not self.held:
            if ratio is None:
                self._armed = False  # 손이 사라지면 다시 벌린 손을 봐야 함
            elif ratio > PINCH_OFF:
                self._armed = True
            elif self._armed and ratio < PINCH_ON:
                self.held = True
                self._bad_since = None
                return "down"
            return None
        # held 상태
        if ratio is not None and ratio <= PINCH_OFF:
            self._bad_since = None
            return None
        kind = "lost" if ratio is None else "release"
        if self._bad_since is None:
            self._bad_since, self._bad_kind = t, kind
            return None
        self._bad_kind = kind
        if t - self._bad_since >= self.release_grace_s:
            self.held = False
            self._bad_since = None
            self._armed = kind == "release"  # 벌려 놓았으면 재무장, 소실이면 다시 벌려야
            return "up" if kind == "release" else "lost"
        return None


class HoldToggle:
    """조건(손바닥 등)을 hold_s 동안 유지하면 True 한 번 반환.

    발동 후에는 조건이 한 번 풀려야(손을 내려야) 다시 장전된다 — 계속 들고
    있으면 재발동하지 않는다. 매 프레임 호출할 것: 손이 안 보이는 프레임도
    condition=False로 호출해야 타이머가 리셋된다. 단 grace_s 이내의 짧은
    검출 끊김은 봐준다 — 웹캠 손 검출은 프레임 단위로 깜빡이기 때문.
    """

    def __init__(self, hold_s=0.6, cooldown_s=1.5, grace_s=0.25):
        self.hold_s = hold_s
        self.cooldown_s = cooldown_s
        self.grace_s = grace_s
        self._since = None
        self._armed = True
        self._last_true = -1e9
        self._last_fire = -1e9

    def update(self, condition, t=None):
        t = time.monotonic() if t is None else t
        if condition:
            self._last_true = t
            if self._since is None:
                self._since = t
            if self._armed and t - self._since >= self.hold_s and t - self._last_fire >= self.cooldown_s:
                self._last_fire = t
                self._armed = False
                return True
        elif t - self._last_true > self.grace_s:
            self._since = None
            self._armed = True
        return False


class GestureStable:
    """같은 제스처가 min_frames 연속 유지될 때만 통과 — 한 프레임 오분류로
    우클릭/스크롤이 발동하는 것을 막는다. 미달이면 'None' 반환."""

    def __init__(self, min_frames=3):
        self.min_frames = min_frames
        self._last = None
        self._count = 0

    def update(self, gesture):
        if gesture == self._last:
            self._count += 1
        else:
            self._last, self._count = gesture, 1
        return gesture if gesture and self._count >= self.min_frames else "None"


def normalize_landmarks(lm_xy):
    """손 랜드마크(21개 x,y) → 위치·크기·회전 불변 특징 벡터(42,).

    손목을 원점으로, 손목→중지MCP 방향을 '위'로 회전 정렬, 그 길이로 스케일.
    카메라 어디서 어떤 각도로 손을 들어도 같은 손모양이면 같은 벡터가 나온다.
    """
    a = np.asarray(lm_xy, dtype=float)
    a = a - a[0]                      # 손목 원점
    v = a[9]                          # 중지 MCP
    ang = math.atan2(v[0], -v[1])     # v를 (0,-1)로 보내는 회전각
    c, s = math.cos(-ang), math.sin(-ang)
    a = a @ np.array([[c, s], [-s, c]])
    return (a / (np.linalg.norm(a[9]) + 1e-9)).ravel()


class CustomGestures:
    """사용자 정의 제스처 저장소 + kNN 분류기.

    등록: gesture_studio.py가 샘플 30개를 수집해 add(). 파일로 영속.
    인식: 내장 분류(7종)가 'None'일 때만 classify()로 2차 판정 —
    내장과 커스텀이 싸우지 않게 하는 우선순위 규칙.
    """

    def __init__(self, path, thresh=0.35):
        import os

        self.path = str(path)
        # ponytail: 최근접(top-1) 거리 임계. 반드시 등록 분리 기준(gesture_studio의
        # CONFUSION_DIST)보다 작아야 두 클래스의 인식 영역이 안 겹친다. 절대값은
        # 실제 MediaPipe 랜드마크 스케일에 의존하므로 실사용 오인식/미인식 보고 보고
        # 조정할 것 (미인식↑면 올리고, 엉뚱한 발화↑면 내린다).
        self.thresh = thresh
        self.X = np.zeros((0, 42))
        self.names = []
        if os.path.exists(self.path):
            # 파일이 있는데 못 읽으면(잠김·손상) 조용히 빈 상태로 시작하면 안 된다 —
            # 다음 add()가 기존 등록을 통째로 덮어쓴다. 예외를 올려 호출자가 알게 한다.
            d = np.load(self.path, allow_pickle=False)
            self.X = d["X"]
            self.names = [str(n) for n in d["names"]]

    @property
    def n(self):
        return len(self.names)

    def class_names(self):
        return sorted(set(self.names))

    def _save(self):
        import os

        tmp = self.path + ".tmp.npz"  # 임시파일→교체: 쓰다 죽어도 기존 파일 안 깨짐
        np.savez(tmp, X=self.X, names=np.array(self.names))
        os.replace(tmp, self.path)

    def add(self, name, feats):
        self.X = np.vstack([self.X, np.asarray(feats, dtype=float)])
        self.names += [name] * len(feats)
        self._save()

    def remove(self, name):
        keep = [i for i, n in enumerate(self.names) if n != name]
        self.X = self.X[keep]
        self.names = [self.names[i] for i in keep]
        self._save()

    def classify(self, lm_xy, k=5):
        """랜드마크 → 커스텀 제스처 이름 또는 None.

        최근접 거리로 먼저 게이트하고(엉뚱한 손모양 기권), 거리 가중 투표로
        라벨을 정한다 — 단순 다수결은 경계에서 먼 샘플에 휘둘려 프레임마다 튄다.
        """
        if self.n == 0:
            return None
        f = normalize_landmarks(lm_xy)
        d = np.linalg.norm(self.X - f, axis=1)
        idx = np.argsort(d)[:k]
        if float(d[idx[0]]) > self.thresh:  # 가장 가까운 샘플조차 멀면 기권
            return None
        w = {}
        for i in idx:
            w[self.names[i]] = w.get(self.names[i], 0.0) + 1.0 / (float(d[i]) + 1e-6)
        return max(w, key=w.get)

    def nearest_class(self, feats):
        """새 샘플 묶음이 기존 클래스와 얼마나 가까운지 → (이름, 최소거리). 혼동도 검사용.

        평균이 아니라 '가장 가까운 샘플 쌍'의 거리를 본다 — 평균을 쓰면 일부
        샘플만 기존 클래스에 딱 붙어 있어도(부분 겹침) 전체 평균에 묻혀 통과한다.
        """
        if self.n == 0:
            return None, float("inf")
        best_name, best_d = None, float("inf")
        for name in self.class_names():
            cls = self.X[[i for i, n in enumerate(self.names) if n == name]]
            dd = float(min(np.linalg.norm(cls - f, axis=1).min() for f in feats))
            if dd < best_d:
                best_name, best_d = name, dd
        return best_name, best_d


class SwipeDetector:
    """빠른 수평 손 쓸기 감지 → 'Swipe_Left' | 'Swipe_Right' | None.

    정지 상태에서만 무장되고, 발동 후엔 다시 정지해야 재무장한다 —
    스와이프 후 제자리로 돌아오는 손이 반대 방향 스와이프로 오인되는 것을
    구조적으로 방지. 좌표는 미러링(셀피) 프레임의 정규화 x라서
    사용자가 자기 오른쪽으로 쓸면 x가 증가한다.
    """

    def __init__(self, dist=0.22, max_t=0.5, still_speed=0.25, still_t=0.25):
        self.dist = dist              # 발동 수평 변위 (화면 폭 비율)
        self.max_t = max_t            # 이 시간 안에 변위를 만들어야 함
        self.still_speed = still_speed  # 무장 조건: 속도(정규화/초)가 이 미만
        self.still_t = still_t          # ...인 상태가 이 시간 유지
        self._hist = collections.deque()
        self._armed = False
        self._still_since = None

    def update(self, anchor, t):
        if anchor is None:  # 손 사라짐 → 리셋 (재등장 후 정지해야 무장)
            self._hist.clear()
            self._armed = False
            self._still_since = None
            return None
        x, y = float(anchor[0]), float(anchor[1])
        self._hist.append((t, x, y))
        while self._hist and t - self._hist[0][0] > self.max_t:
            self._hist.popleft()
        ref = next((p for p in reversed(self._hist) if t - p[0] >= 0.08), self._hist[0])
        speed = math.hypot(x - ref[1], y - ref[2]) / max(t - ref[0], 1e-3)
        if not self._armed:
            if speed < self.still_speed:
                if self._still_since is None:
                    self._still_since = t
                elif t - self._still_since >= self.still_t:
                    self._armed = True
                    # 무장 이후의 움직임만 인정 — 이력을 리셋하지 않으면
                    # "빠른 이동 후 정지"가 소급 스와이프로 오발동한다
                    self._hist.clear()
                    self._hist.append((t, x, y))
            else:
                self._still_since = None
            return None
        for (t0, x0, y0) in self._hist:
            dx, dy = x - x0, y - y0
            if abs(dx) >= self.dist and abs(dy) < abs(dx) * 0.6:  # 수평 위주 이동만
                self._armed = False
                self._still_since = None
                self._hist.clear()
                return "Swipe_Right" if dx > 0 else "Swipe_Left"
        return None


class GestureEngine:
    """GestureRecognizer(VIDEO 모드) 래퍼. frame(BGR, 미러링됨) → parse_hand 결과."""

    def __init__(self, model_path):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python.vision import (
            GestureRecognizer,
            GestureRecognizerOptions,
            RunningMode,
        )

        self._mp = mp
        # 경로 대신 바이트로 로드 — 네이티브 라이브러리가 한글 경로를 못 열기 때문
        model_buf = open(model_path, "rb").read()
        self.recognizer = GestureRecognizer.create_from_options(
            GestureRecognizerOptions(
                base_options=BaseOptions(model_asset_buffer=model_buf),
                running_mode=RunningMode.VIDEO,
                num_hands=1,
                # 기본 0.5는 책상 거리(팔 길이 밖) 작은 손을 자주 놓친다
                min_hand_detection_confidence=0.3,
                min_hand_presence_confidence=0.3,
                min_tracking_confidence=0.3,
            )
        )
        self._last_ts = 0

    def hand(self, frame_bgr, ts_ms=None):
        import cv2

        if ts_ms is None:
            ts_ms = int(time.monotonic() * 1000)
        ts_ms = max(ts_ms, self._last_ts + 1)
        self._last_ts = ts_ms
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        return parse_hand(self.recognizer.recognize_for_video(img, ts_ms))
