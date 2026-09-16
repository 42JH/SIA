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


# Screen_Next/Prev는 실측 도구와 실제 assistant가 반드시 같은 값을 사용한다.
SCREEN_SWIPE_CONFIG = {
    "dist": 0.12,
    "max_t": 0.90,
    "still_t": 0.18,
    "horizontal_ratio": 1.0,
    "vertical": False,
}

# 스와이프/스크롤/핀치볼륨의 이동량 기준(dist, step_dist 등)은 전부 화면
# 비율(정규화 좌표)로 정해져 있어, 카메라와의 거리에 따라 같은 물리적 동작도
# 다르게 판정된다 — 가까이 있으면 작은 움직임도 크게 잡히고, 멀리 있으면 큰
# 움직임도 작게 잡힌다. 이 기준값들은 손 크기가 대략 이 정도(REFERENCE_PALM_SIZE)
# 일 때를 기준으로 골랐다고 보고, 실제 손 크기가 다르면 좌표를 그 비율만큼
# 스케일링해서 감지기에 넣는다 — 감지기 내부 기준값 자체는 건드리지 않는다.
REFERENCE_PALM_SIZE = 0.12


def scale_by_hand_size(point, size, reference=REFERENCE_PALM_SIZE):
    """손 크기(size)를 기준 크기(reference)로 맞추도록 좌표 한 점을 스케일링한다.

    size가 기준보다 크면(카메라에 가까움) 좌표를 줄이고, 작으면(멀리 있음)
    늘려서 — 같은 물리적 이동이 카메라 거리와 무관하게 같은 값으로 보이게 한다.
    """
    factor = reference / max(float(size), 1e-6)
    return (point[0] * factor, point[1] * factor)


def scale_landmarks_by_hand_size(landmarks, size, reference=REFERENCE_PALM_SIZE):
    """scale_by_hand_size와 같은 보정을 손 랜드마크 전체에 적용한다.

    모든 점에 같은 배율을 곱하므로, 이미 스케일 불변인 값(예: 핀치 비율 —
    손 크기로 나눈 값)은 분자·분모가 같이 스케일돼 결과가 그대로 유지된다.
    """
    factor = reference / max(float(size), 1e-6)
    return [(x * factor, y * factor) for x, y in landmarks]


def parse_hand(result):
    """GestureRecognizerResult → dict(anchor, pinch_ratio, gesture) / 손 없으면 None.

    anchor는 중지 MCP(9): 핀치 중에도 안정적으로 움직임을 대표하는 지점.
    """
    if not result.hand_landmarks:
        return None
    lm = result.hand_landmarks[0]
    size = _dist(lm[0], lm[9]) + 1e-6
    gesture, score = "None", None
    if result.gestures and result.gestures[0]:
        gesture = result.gestures[0][0].category_name
        score = round(float(result.gestures[0][0].score), 3)
    return {
        "anchor": (lm[9].x, lm[9].y),
        "pinch_ratio": _dist(lm[4], lm[8]) / size,
        "gesture": gesture,
        "score": score,  # 통계용 신뢰도 — MediaPipe 원본, None이면 감지 없음
        "landmarks": [(p.x, p.y) for p in lm],  # HUD 디버그 표시용
        "size": size,  # 손목→중지MCP 거리 — 카메라 거리 보정(scale_by_hand_size)용
    }


def parse_hands(result):
    """Return every detected hand in the shared gesture dictionary format."""
    if not result.hand_landmarks:
        return []
    hands = []
    for idx, lm in enumerate(result.hand_landmarks):
        size = _dist(lm[0], lm[9]) + 1e-6
        gesture, score = "None", None
        if result.gestures and len(result.gestures) > idx and result.gestures[idx]:
            gesture = result.gestures[idx][0].category_name
            score = round(float(result.gestures[idx][0].score), 3)
        handedness = "Unknown"
        if (getattr(result, "handedness", None) and len(result.handedness) > idx
                and result.handedness[idx]):
            handedness = result.handedness[idx][0].category_name
        hands.append({
            "anchor": (lm[9].x, lm[9].y),
            "pinch_ratio": _dist(lm[4], lm[8]) / size,
            "gesture": gesture,
            "score": score,  # 통계용 신뢰도 — MediaPipe 원본, None이면 감지 없음
            "handedness": handedness,
            "landmarks": [(p.x, p.y) for p in lm],
            "size": size,  # 손목→중지MCP 거리 — 카메라 거리 보정(scale_by_hand_size)용
        })
    return hands


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

    def __init__(self, min_frames=3, missing_grace_s=0.0):
        self.min_frames = min_frames
        self.missing_grace_s = missing_grace_s
        self._last = None
        self._count = 0
        self._stable = "None"
        self._missing_since = None

    def update(self, gesture, t=None):
        """Return a stable label, tolerating brief hand-tracking dropouts.

        A transient ``None`` while the user holds a static gesture must not
        re-arm a media toggle. A different detected label still resets
        immediately, so changing poses remains deliberate.
        """
        t = time.monotonic() if t is None else t
        if gesture in (None, "None") and self._stable != "None" and self.missing_grace_s > 0:
            if self._missing_since is None:
                self._missing_since = t
            if t - self._missing_since < self.missing_grace_s:
                return self._stable
        else:
            self._missing_since = None
        if gesture == self._last:
            self._count += 1
        else:
            self._last, self._count = gesture, 1
        self._stable = gesture if gesture and self._count >= self.min_frames else "None"
        return self._stable


class PalmControlMode:
    """Open_Palm 유지로 제어 모드에 진입하고 손을 내리면 종료한다."""

    def __init__(self, enter_hold_s=0.45, leave_s=0.55):
        self.enter_hold_s = enter_hold_s
        self.leave_s = leave_s
        self.active = False
        self._palm_since = None
        self._missing_since = None

    def update(self, gesture, hand_present, t):
        if not self.active:
            if gesture == "Open_Palm":
                if self._palm_since is None:
                    self._palm_since = t
                elif t - self._palm_since >= self.enter_hold_s:
                    self.active = True
                    self._palm_since = None
                    return "entered"
            else:
                self._palm_since = None
            return None
        if hand_present:
            self._missing_since = None
        else:
            if self._missing_since is None:
                self._missing_since = t
            elif t - self._missing_since >= self.leave_s:
                self.active = False
                self._missing_since = None
                return "exited"
        return None


FINGERTIPS = (4, 8, 12, 16, 20)  # MediaPipe 손 랜드마크: 엄지·검지·중지·약지·소지 끝
# 손모양을 구분짓는 정보는 대부분 손끝에 몰려 있고 손목·손바닥은 거의 안 움직인다.
# 손끝에 2배 가중치를 줘 "손모양은 비슷한데 손가락만 다른" 케이스의 구분력을 올린다.
LANDMARK_WEIGHTS = np.ones(21, dtype=np.float64)
LANDMARK_WEIGHTS[list(FINGERTIPS)] = 2.0


def weighted_distance(diff):
    """diff: (..., 42) 정규화 특징 벡터 차이 → 손끝 가중 L2 거리.

    가중치 평균이 1(균등 가중)일 때 np.linalg.norm(diff, axis=-1)과 정확히
    같은 값이 나오도록 스케일을 보존한다 — 그래야 CustomGestures.thresh(0.35)
    같은 기존 임계값을 재조정 없이 그대로 쓸 수 있다.
    """
    per_landmark = diff.reshape(diff.shape[:-1] + (21, 2))
    sq = np.sum(per_landmark ** 2, axis=-1)  # (..., 21) 랜드마크별 제곱거리
    weighted_sq_sum = 21 * np.average(sq, axis=-1, weights=LANDMARK_WEIGHTS)
    return np.sqrt(weighted_sq_sum)


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


def pose_distances(templates, feature):
    """회전 정렬된 한 손 자세를 원본/좌우 반전 중 가까운 쪽으로 비교한다.

    기존 저장 특징은 수정하지 않으므로 반대 손으로 찍은 예전 템플릿도 지원한다.
    """
    mirrored = np.array(feature, copy=True)
    mirrored[0::2] *= -1
    return np.minimum(weighted_distance(templates - feature),
                      weighted_distance(templates - mirrored))


class CustomGestures:
    """사용자 정의 제스처 저장소 + kNN 분류기.

    등록: gesture_studio.py가 샘플 30개를 수집해 add(). 파일로 영속.
    인식: 내장 분류(7종)가 'None'일 때만 classify()로 2차 판정 —
    내장과 커스텀이 싸우지 않게 하는 우선순위 규칙.
    """

    def __init__(self, path, thresh=0.35):
        import os

        self.path = str(path)
        # NOTE(한계): 최근접(top-1) 거리 임계. 반드시 등록 분리 기준(gesture_studio의
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

    def classify_with_distance(self, lm_xy, k=5):
        """Return a custom label and its nearest template distance.

        The normal rejection threshold remains unchanged.  Callers can use a
        successful result to distinguish a confident registered pose from a
        weak built-in classifier guess.
        """
        if self.n == 0:
            return None, float("inf")
        f = normalize_landmarks(lm_xy)
        d = pose_distances(self.X, f)
        idx = np.argsort(d)[:k]
        nearest = float(d[idx[0]])
        if nearest > self.thresh:
            return None, nearest
        weights = {}
        for i in idx:
            weights[self.names[i]] = weights.get(self.names[i], 0.0) + 1.0 / (float(d[i]) + 1e-6)
        return max(weights, key=weights.get), nearest

    def classify(self, lm_xy, k=5):
        """랜드마크 → 커스텀 제스처 이름 또는 None.

        최근접 거리로 먼저 게이트하고(엉뚱한 손모양 기권), 거리 가중 투표로
        라벨을 정한다 — 단순 다수결은 경계에서 먼 샘플에 휘둘려 프레임마다 튄다.
        """
        if self.n == 0:
            return None
        f = normalize_landmarks(lm_xy)
        d = pose_distances(self.X, f)
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
            dd = float(min(pose_distances(cls, f).min() for f in feats))
            if dd < best_d:
                best_name, best_d = name, dd
        return best_name, best_d


class MotionHandTracker:
    """검출 순서가 아니라 손 정체성(handedness)으로 한 손을 계속 추적한다.

    MediaPipe는 프레임마다 Left/Right 검출 순서가 바뀔 수 있어, 손 목록의
    첫 번째를 그대로 스와이프에 먹이면 위치가 안 변해도 순서만 바뀐 것을
    이동으로 오인할 수 있다. 이 클래스는 현재 추적 중인 라벨을 목록 순서와
    무관하게 찾아 반환하고, 그 라벨을 잃거나(손 소실) 새 라벨로 바뀌면
    ``changed=True``를 돌려줘 호출자가 스와이프 상태를 리셋하게 한다.
    """

    def __init__(self):
        self._label = None

    def update(self, hands):
        hands = hands or []
        if self._label is not None:
            match = next((h for h in hands if h.get("handedness") == self._label), None)
            if match is not None:
                return match, False
        if not hands:
            changed = self._label is not None
            self._label = None
            return None, changed
        chosen = hands[0]
        self._label = chosen.get("handedness")
        return chosen, True


class SwipeDetector:
    """빠른 손 쓸기 감지 → Swipe_Left/Right/Up/Down | None.

    정지 상태에서만 무장된다. 좌/우 탐색 스와이프는 방향 잠금을 사용한다:
    발동 뒤 시작 위치로 돌아오는 움직임은 무시하고 같은 방향은 빠르게 반복한다.
    반대 방향으로 바꾸려면 시작 위치에서 0.5초 정지해 잠금을 해제한다.
    상/하 볼륨 스와이프도 복귀 오인식 방지를 위해 hand loss 뒤에만 재무장한다.
    좌표는 미러링(셀피) 프레임의 정규화 x라서 사용자가 자기 오른쪽으로 쓸면
    x가 증가한다.
    """

    def __init__(self, dist=0.22, max_t=0.5, still_speed=0.25, still_t=0.25,
                 horizontal=True, vertical=True, horizontal_ratio=0.6,
                 vertical_requires_hand_loss=True):
        self.dist = dist              # 발동 변위 (정규화 화면 비율)
        self.max_t = max_t            # 이 시간 안에 변위를 만들어야 함
        self.still_speed = still_speed  # 무장 조건: 속도(정규화/초)가 이 미만
        self.still_t = still_t          # ...인 상태가 이 시간 유지
        self.horizontal = horizontal
        self.vertical = vertical
        self.horizontal_ratio = horizontal_ratio
        self.vertical_requires_hand_loss = vertical_requires_hand_loss
        self._hist = collections.deque()
        self._armed = False
        self._still_since = None
        self._await_hand_loss = False  # 상/하 스와이프 뒤 손을 내리기 전에는 이동 무시
        self._horiz_lock = None        # 'Swipe_Left' | 'Swipe_Right' | None
        self._return_home = None       # (x, y): 수평 스와이프를 시작했던 위치
        self._lock_home = None         # 방향 전환을 위한 중앙 정지 위치
        self._home_since = None
        self.return_tol = dist * 0.20  # 시작 위치로 돌아왔다고 보는 허용 오차
        self.unlock_hold_s = 0.5
        # Horizontal swipes do not require a return to their original point.
        # A short post-command lock absorbs the return motion; a new still
        # position then becomes the next gesture's neutral anchor.
        self.cooldown_s = 0.20
        self.rearm_hold_s = 0.15
        self._cooldown_until = 0.0
        self._direction_lock = None
        self._resume_after_cooldown = False
        self._lock_still_since = None
        self._last_point = None  # (t, x, y) 직전 프레임 — 클리어와 무관하게 유지
        self._input_scale = None

    def prime(self, anchor, t):
        """이미 손바닥 홀드로 확인된 위치에서 즉시 스와이프를 받을 준비를 한다."""
        self.update(None, t)
        if anchor is None:
            return
        x, y = float(anchor[0]), float(anchor[1])
        self._armed = True
        self._hist.append((t, x, y))

    def update(self, anchor, t, size=None):
        # 추적 시작 시 배율을 고정한다. 매 프레임 절대 좌표의 배율을 바꾸면
        # 크기 추정 변화만으로 가짜 좌우 이동이 생긴다.
        if anchor is None:
            self._input_scale = None
        elif size is not None:
            if self._input_scale is None:
                self._input_scale = REFERENCE_PALM_SIZE / max(float(size), 1e-6)
            anchor = tuple(float(v) * self._input_scale for v in anchor)
        if anchor is None:  # 손 사라짐 → 리셋 (재등장 후 정지해야 무장)
            self._hist.clear()
            self._armed = False
            self._still_since = None
            self._await_hand_loss = False
            self._horiz_lock = None
            self._return_home = None
            self._lock_home = None
            self._home_since = None
            self._cooldown_until = 0.0
            self._direction_lock = None
            self._resume_after_cooldown = False
            self._lock_still_since = None
            self._last_point = None
            return None
        if self._await_hand_loss:
            return None
        x, y = float(anchor[0]), float(anchor[1])
        prev_point = self._last_point
        self._last_point = (t, x, y)
        self._hist.append((t, x, y))
        while self._hist and t - self._hist[0][0] > self.max_t:
            self._hist.popleft()
        ref = next((p for p in reversed(self._hist) if t - p[0] >= 0.08), self._hist[0])
        speed = math.hypot(x - ref[1], y - ref[2]) / max(t - ref[0], 1e-3)
        if t < self._cooldown_until:
            self._armed = False
            self._still_since = None
            self._hist.clear()
            self._resume_after_cooldown = True
            return None
        # 직전 프레임 대비 순간 이동량 — speed(약 0.08초 전 표본과 비교)와 달리
        # 주기적인 작은 흔들림에 상쇄돼 0으로 보이는 일이 없어, "진짜로 멈췄는가"
        # 판단에 더 안전하다.
        step_speed = (math.hypot(x - prev_point[1], y - prev_point[2]) / max(t - prev_point[0], 1e-3)
                      if prev_point is not None else speed)
        if self._resume_after_cooldown:
            self._resume_after_cooldown = False
            # 쿨다운이 끝난 시점에도 발동 때와 같은 방향으로 계속 빠르게
            # 움직이는 중이면 하나의 연속 동작이 이어지는 것이다 — 무장하지
            # 않고 멈춤(또는 방향 전환)을 기다린다. 이미 느려졌거나 반대로
            # 되돌아가는 중이라면(복귀 동작) 바로 재무장해, 복귀 뒤 같은 방향
            # 빠른 반복이나 반대 방향 재개를 즉시 받을 수 있게 한다.
            expected_sign = 1 if self._direction_lock == "Swipe_Right" else -1
            moving_same_way = prev_point is not None and (x - prev_point[1]) * expected_sign > 0
            same_motion_continuing = moving_same_way and step_speed >= self.still_speed
            self._hist.clear()
            self._hist.append((t, x, y))
            if not same_motion_continuing:
                self._armed = True
            return None
        if self._direction_lock is not None:
            # 방향 잠금 해제는 직전 한 프레임 사이의 실제 이동량으로만 판단한다.
            # speed는 ~0.08초 전 표본과 비교하므로, 그 간격과 주기가 맞아
            # 떨어지는 작은 좌우 흔들림은 변위가 우연히 상쇄돼 0으로 보일 수
            # 있다 — 그러면 흔들림을 정지로 오인해 잠금을 풀고, 복귀 동작이
            # 새 반대 방향 명령으로 잘못 발동한다.
            if step_speed < self.still_speed * 0.5:
                if self._lock_still_since is None:
                    self._lock_still_since = t
                elif t - self._lock_still_since >= self.rearm_hold_s:
                    self._direction_lock = None
            else:
                self._lock_still_since = None
        # 수평 스와이프 후 시작 위치로 복귀하는 구간. 복귀 경로는 어떤 방향이든
        # 명령으로 해석하지 않는다. 시작 위치에 닿으면 즉시 같은 방향 반복을 허용한다.
        if self._return_home is not None:
            hx, hy = self._return_home
            if math.hypot(x - hx, y - hy) <= self.return_tol:
                self._return_home = None
                self._home_since = None
                self._armed = True
                self._hist.clear()
                self._hist.append((t, x, y))
            return None
        # 시작 위치에서 의도적으로 오래 멈추면 방향 잠금을 푼다.
        if self._horiz_lock is not None and self._lock_home is not None:
            hx, hy = self._lock_home
            if math.hypot(x - hx, y - hy) <= self.return_tol and speed < self.still_speed:
                if self._home_since is None:
                    self._home_since = t
                elif t - self._home_since >= self.unlock_hold_s:
                    self._horiz_lock = None
                    self._lock_home = None
                    self._home_since = None
            else:
                self._home_since = None
        if not self._armed:
            if speed < self.still_speed:
                if self._still_since is None:
                    self._still_since = t
                elif t - self._still_since >= self.rearm_hold_s:
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
            if not self.horizontal and abs(dx) >= self.dist and abs(dy) < abs(dx) * 0.6:
                continue
            if (self.horizontal and abs(dx) >= self.dist
                    and abs(dy) < abs(dx) * self.horizontal_ratio):  # 수평 위주 이동만
                direction = "Swipe_Right" if dx > 0 else "Swipe_Left"
                if (self._direction_lock is not None
                        and direction != self._direction_lock):
                    # Ignore the return path, but keep tracking so a quick
                    # same-direction repeat can start from this turning point.
                    self._hist.clear()
                    self._hist.append((t, x, y))
                    self._armed = True
                    self._still_since = None
                    return None
                self._armed = False
                self._still_since = None
                self._hist.clear()
                self._home_since = None
                # 복귀 후 반대 방향으로 쓸면 새 명령이 아니라 되돌림으로 간주한다.
                # 시작 위치에서 0.5초 정지하면 방향 잠금이 해제돼 전환할 수 있다.
                self._direction_lock = direction
                self._cooldown_until = t + self.cooldown_s
                return direction
            if self.vertical and abs(dy) >= self.dist and abs(dx) < abs(dy) * 0.6:  # 수직 위주 이동만
                self._armed = False
                self._still_since = None
                self._hist.clear()
                # 볼륨 조절은 손을 원위치로 돌리는 동작이 반대 방향 명령이 되기 쉬워
                # 손을 프레임 밖으로 내린 뒤에만 다음 명령을 허용한다.
                self._await_hand_loss = self.vertical_requires_hand_loss
                if not self.vertical_requires_hand_loss:
                    self._return_home = (x0, y0)
                # 이미지 좌표 y는 아래로 갈수록 커진다.
                return "Swipe_Down" if dy > 0 else "Swipe_Up"
        return None


class PalmScrollDetector:
    """편 손의 세로 이동을 누적해 연속 마우스 휠 단계로 바꾼다.

    위로 손을 움직이면 양수(페이지 위), 아래로 움직이면 음수(페이지 아래)를
    반환한다. 한 방향으로 움직이는 동안만 누적하고, 방향을 바꾸려면 잠시 멈춰야
    한다. 공중에서 손을 원위치로 되돌릴 때 반대 방향으로 스크롤되는 것을 막는다.
    """

    def __init__(self, arm_t=0.18, step_dist=0.020, still_t=0.30, enabled=False):
        # 기본 제공 제스처는 MediaPipe 7종과 좌/우 스와이프만이다.
        # 연속 스크롤은 향후 등록형 커스텀 동작으로만 활성화한다.
        self.enabled = enabled
        self.arm_t = arm_t
        self.step_dist = step_dist
        self.still_t = still_t
        self.reset()

    def reset(self):
        self._since = None
        self._last_y = None
        self._residual = 0.0
        self._direction = 0
        self._still_since = None

    def prime(self, anchor, t):
        """제어 모드 진입 시 이미 안정된 손 위치로 즉시 준비한다."""
        self.reset()
        if anchor is not None:
            self._last_y = float(anchor[1])
            self._since = t - self.arm_t

    def update(self, anchor, t):
        if not self.enabled:
            self.reset()
            return 0
        if anchor is None:
            self.reset()
            return 0
        y = float(anchor[1])
        if self._last_y is None:
            self._last_y = y
            self._since = t
            return 0
        dy = self._last_y - y  # 손을 위로 올림 = 콘텐츠도 위로
        self._last_y = y
        if t - self._since < self.arm_t:
            return 0

        # 방향 전환은 잠깐 멈춘 뒤에만 허용한다. 되돌림 동작은 무시한다.
        if abs(dy) < 0.002:
            if self._still_since is None:
                self._still_since = t
            elif t - self._still_since >= self.still_t:
                self._direction = 0
                self._residual = 0.0
            return 0
        self._still_since = None
        direction = 1 if dy > 0 else -1
        if self._direction and direction != self._direction:
            return 0
        self._direction = direction
        self._residual += abs(dy)
        steps = min(3, int(self._residual / self.step_dist))
        if not steps:
            return 0
        self._residual -= steps * self.step_dist
        return direction * steps


class FingerSwipeDetector:
    """손목 고정형 스와이프 실험기.

    손목(0번 랜드마크)의 화면 좌표는 거의 유지한 채, 중지 끝(12번)의 손목 상대
    좌표가 좌우로 빠르게 움직일 때 Finger_Swipe_Left/Right를 낸다. 손 전체를
    옮기는 SwipeDetector와는 다른 UX 가설을 검증하기 위한 별도 감지기다.
    같은 방향은 빠르게 반복하고, 손목 대비 시작 위치에서 0.5초 정지했을 때만
    반대 방향 전환을 허용한다. 실제 실행 매핑에는 실측 통과 전까지 연결하지 않는다.
    """

    def __init__(self, tip_dist=0.12, wrist_drift=0.06, max_t=0.5,
                 still_speed=0.18, still_t=0.25):
        self.tip_dist = tip_dist
        self.wrist_drift = wrist_drift
        self.max_t = max_t
        self.still_speed = still_speed
        self.still_t = still_t
        self._hist = collections.deque()
        self._armed = False
        self._still_since = None
        self._horiz_lock = None
        self._return_home = None      # 손목 대비 중지 끝의 시작 상대 좌표
        self._lock_home = None
        self._home_since = None
        self.return_tol = tip_dist * 0.20
        self.unlock_hold_s = 0.5

    def update(self, lm_xy, t):
        if lm_xy is None:
            self._hist.clear()
            self._armed = False
            self._still_since = None
            self._horiz_lock = None
            self._return_home = None
            self._lock_home = None
            self._home_since = None
            return None
        wrist = lm_xy[0]
        tips = [lm_xy[i] for i in (8, 12, 16, 20)]
        tip = (sum(float(p[0]) for p in tips) / len(tips),
               sum(float(p[1]) for p in tips) / len(tips))
        wx, wy = float(wrist[0]), float(wrist[1])
        rx, ry = float(tip[0]) - wx, float(tip[1]) - wy
        self._hist.append((t, wx, wy, rx, ry))
        while self._hist and t - self._hist[0][0] > self.max_t:
            self._hist.popleft()
        ref = next((p for p in reversed(self._hist) if t - p[0] >= 0.08), self._hist[0])
        wrist_speed = math.hypot(wx - ref[1], wy - ref[2]) / max(t - ref[0], 1e-3)
        tip_speed = math.hypot(rx - ref[3], ry - ref[4]) / max(t - ref[0], 1e-3)
        # 스와이프 뒤 손목 대비 시작 위치로 돌아오는 경로는 명령으로 쓰지 않는다.
        if self._return_home is not None:
            hx, hy = self._return_home
            if math.hypot(rx - hx, ry - hy) <= self.return_tol:
                self._return_home = None
                self._home_since = None
                self._armed = True
                self._hist.clear()
                self._hist.append((t, wx, wy, rx, ry))
            return None
        # 시작 상대 위치에서 의도적으로 오래 멈추면 반대 방향 전환을 허용한다.
        if self._horiz_lock is not None and self._lock_home is not None:
            hx, hy = self._lock_home
            if (math.hypot(rx - hx, ry - hy) <= self.return_tol
                    and wrist_speed < self.still_speed and tip_speed < self.still_speed):
                if self._home_since is None:
                    self._home_since = t
                elif t - self._home_since >= self.unlock_hold_s:
                    self._horiz_lock = None
                    self._lock_home = None
                    self._home_since = None
            else:
                self._home_since = None
        if not self._armed:
            if wrist_speed < self.still_speed and tip_speed < self.still_speed:
                if self._still_since is None:
                    self._still_since = t
                elif t - self._still_since >= self.still_t:
                    self._armed = True
                    self._hist.clear()
                    self._hist.append((t, wx, wy, rx, ry))
            else:
                self._still_since = None
            return None
        for t0, w0x, w0y, r0x, r0y in self._hist:
            dx, dy = rx - r0x, ry - r0y
            # 손목이 조금 따라 움직여도, 손목 대비 손가락 방향이 바뀐 경우만 본다.
            # 따라서 손 전체를 화면에서 옮기기만 한 동작은 dx가 거의 0이라 무시된다.
            if abs(dx) >= self.tip_dist and abs(dy) < abs(dx) * 0.8:
                direction = "Finger_Swipe_Right" if dx > 0 else "Finger_Swipe_Left"
                self._armed = False
                self._still_since = None
                self._hist.clear()
                self._home_since = None
                if self._horiz_lock is not None and direction != self._horiz_lock:
                    self._return_home = self._lock_home or (r0x, r0y)
                    return None
                self._horiz_lock = direction
                self._lock_home = (r0x, r0y)
                self._return_home = (r0x, r0y)
                return direction
        return None


class PinchVolumeDetector:
    """핀치한 손을 위/아래로 움직여 Volume_Up/Volume_Down을 내는 감지기.

    엄지 끝(4)과 검지 끝(8)이 붙은 상태를 0.18초 유지해야 조절이 시작된다.
    핀치 중 손바닥 기준점(중지 MCP, 9)을 위/아래로 0.08 화면 비율 움직이면
    한 단계 이벤트를 한 번만 낸다. 손가락을 펴야 다음 조절이 가능하므로,
    실행 뒤 손을 원위치로 내리는 복귀 동작은 볼륨 감소로 해석하지 않는다.
    """

    def __init__(self, pinch_on=0.35, pinch_off=0.55, arm_t=0.18,
                 step_dist=0.08, cooldown_s=0.16, enabled=False):
        # 핀치 볼륨은 기본 제공 명령이 아니다. 커스텀 등록 경로에서만 켠다.
        self.enabled = enabled
        self.pinch_on = pinch_on
        self.pinch_off = pinch_off
        self.arm_t = arm_t
        self.step_dist = step_dist
        self.cooldown_s = cooldown_s
        self._pinched = False
        self._consumed = False
        self._pinch_since = None
        self._baseline_y = None
        self._last_fire = -float("inf")

    def reset(self):
        self._pinched = False
        self._consumed = False
        self._pinch_since = None
        self._baseline_y = None

    def update(self, lm_xy, t):
        if not self.enabled:
            self.reset()
            return None
        if lm_xy is None:
            self.reset()
            return None
        wrist = lm_xy[0]
        middle_mcp = lm_xy[9]
        thumb_tip = lm_xy[4]
        index_tip = lm_xy[8]
        scale = math.hypot(float(middle_mcp[0]) - float(wrist[0]),
                           float(middle_mcp[1]) - float(wrist[1]))
        if scale < 1e-4:
            return None
        pinch_ratio = math.hypot(float(thumb_tip[0]) - float(index_tip[0]),
                                 float(thumb_tip[1]) - float(index_tip[1])) / scale
        y = float(middle_mcp[1])
        if not self._pinched:
            if pinch_ratio <= self.pinch_on:
                if self._pinch_since is None:
                    self._pinch_since = t
                elif t - self._pinch_since >= self.arm_t:
                    self._pinched = True
                    self._baseline_y = y
            else:
                self._pinch_since = None
            return None
        if pinch_ratio >= self.pinch_off:
            self.reset()
            return None
        if self._consumed:
            return None
        dy = y - self._baseline_y
        if t - self._last_fire >= self.cooldown_s and abs(dy) >= self.step_dist:
            self._baseline_y = y
            self._last_fire = t
            self._consumed = True
            # 카메라 좌표 y는 아래로 갈수록 커진다.
            return "Volume_Down" if dy > 0 else "Volume_Up"
        return None


class PointerControlDetector:
    """검지 포인팅 상태에서의 좌/우 화면 넘김과 상/하 연속 볼륨 제어.

    검지만 편 자세를 0.25초 유지해 기준 위치를 잡는다. 그 뒤 검지 포인팅 손을
    좌/우로 움직이면 Screen_Next/Screen_Prev를 한 번 내고 기준 위치 복귀 후
    같은 방향을 반복할 수 있다. 위/아래 이동은 포인팅을 유지하는 동안 0.4초마다
    Volume_Up/Volume_Down을 반복한다. 볼륨 조절 후 반대 방향 복귀는 포인팅을
    풀기 전까지 무시해 원위치 이동이 반대 볼륨 명령이 되는 것을 막는다.
    """

    def __init__(self, arm_t=0.25, still_speed=0.18, horizontal_dist=0.12,
                 vertical_dist=0.08, repeat_s=0.40):
        self.arm_t = arm_t
        self.still_speed = still_speed
        self.horizontal_dist = horizontal_dist
        self.vertical_dist = vertical_dist
        self.repeat_s = repeat_s
        self._armed = False
        self._still_since = None
        self._last_anchor = None
        self._home = None
        self._mode = None              # None | 'horizontal' | 'vertical'
        self._locked_direction = None
        self._last_fire = -float("inf")

    def reset(self):
        self._armed = False
        self._still_since = None
        self._last_anchor = None
        self._home = None
        self._mode = None
        self._locked_direction = None

    @staticmethod
    def _dist(a, b):
        return math.hypot(float(a[0]) - float(b[0]), float(a[1]) - float(b[1]))

    def _is_index_pointing(self, lm):
        wrist, middle_mcp = lm[0], lm[9]
        palm = self._dist(wrist, middle_mcp)
        if palm < 1e-4:
            return False
        index_len = self._dist(lm[5], lm[8])
        folded = max(self._dist(lm[mcp], lm[tip])
                     for mcp, tip in ((9, 12), (13, 16), (17, 20)))
        # 검지는 손바닥 길이 이상 펴지고, 나머지 세 손가락은 검지보다 확실히 짧다.
        return index_len >= palm * 0.80 and folded <= index_len * 0.75

    def update(self, lm_xy, t):
        if lm_xy is None or not self._is_index_pointing(lm_xy):
            self.reset()
            return None
        anchor = (float(lm_xy[9][0]), float(lm_xy[9][1]))  # 손가락이 아닌 손바닥 이동
        if not self._armed:
            if self._last_anchor is None:
                self._last_anchor = (t, *anchor)
                self._still_since = t
                return None
            dt = max(t - self._last_anchor[0], 1e-3)
            speed = math.hypot(anchor[0] - self._last_anchor[1],
                               anchor[1] - self._last_anchor[2]) / dt
            self._last_anchor = (t, *anchor)
            if speed <= self.still_speed:
                if t - self._still_since >= self.arm_t:
                    self._armed = True
                    self._home = anchor
            else:
                self._still_since = t
            return None

        hx, hy = self._home
        dx, dy = anchor[0] - hx, anchor[1] - hy
        # 화면 넘김 뒤 기준 위치에 돌아오면 다음 넘김을 즉시 다시 무장한다.
        if self._mode == "horizontal":
            if math.hypot(dx, dy) <= self.horizontal_dist * 0.30:
                self._mode = None
                self._home = anchor
            return None
        # 볼륨은 같은 방향만 반복한다. 반대쪽으로 복귀해도 포인팅을 풀기 전엔 무시한다.
        if self._mode == "vertical":
            if t - self._last_fire >= self.repeat_s:
                if self._locked_direction == "up" and dy <= -self.vertical_dist:
                    self._last_fire = t
                    return "Volume_Up"
                if self._locked_direction == "down" and dy >= self.vertical_dist:
                    self._last_fire = t
                    return "Volume_Down"
            return None
        if abs(dx) >= self.horizontal_dist and abs(dx) >= abs(dy) * 0.9:
            self._mode = "horizontal"
            return "Screen_Next" if dx < 0 else "Screen_Prev"
        if abs(dy) >= self.vertical_dist and abs(dy) > abs(dx) * 1.1:
            self._mode = "vertical"
            self._locked_direction = "up" if dy < 0 else "down"
            self._last_fire = t
            return "Volume_Up" if dy < 0 else "Volume_Down"
        return None


class TwoHandSpreadDetector:
    """Detect one intentional two-hand spread/close motion.

    The distance between palm centres is normalised by mean palm size, which
    makes the detector less sensitive to the user's distance from the camera.
    One event requires both hands to leave the frame before it can re-arm;
    this prevents the return motion from becoming the opposite command.
    """

    def __init__(self, still_s=0.25, still_speed=1.2, delta=1.25, max_t=1.0,
                 enabled=False):
        # 양손 벌림/모음도 등록형 커스텀 제스처로 분리한다.
        self.enabled = enabled
        self.still_s = still_s
        self.still_speed = still_speed
        self.delta = delta
        self.max_t = max_t
        self.reset()

    def reset(self):
        self._last = None
        self._still_since = None
        self._baseline = None
        self._armed_at = None
        self._wait_for_loss = False

    @staticmethod
    def _measure(hands):
        if len(hands) < 2:
            return None
        palms = []
        sizes = []
        for hand in hands[:2]:
            lm = hand["landmarks"]
            points = [lm[i] for i in (0, 5, 9, 13, 17)]
            palms.append((sum(p[0] for p in points) / len(points),
                          sum(p[1] for p in points) / len(points)))
            sizes.append(math.hypot(lm[0][0] - lm[9][0], lm[0][1] - lm[9][1]))
        scale = max(sum(sizes) / len(sizes), 1e-4)
        return math.hypot(palms[0][0] - palms[1][0], palms[0][1] - palms[1][1]) / scale

    def update(self, hands, t=None):
        if not self.enabled:
            self.reset()
            return None
        t = time.monotonic() if t is None else t
        value = self._measure(hands)
        if value is None:
            self.reset()
            return None
        if self._wait_for_loss:
            return None

        if self._last is None:
            self._last = (t, value)
            return None
        dt = max(t - self._last[0], 1e-3)
        speed = abs(value - self._last[1]) / dt
        self._last = (t, value)

        if self._baseline is None:
            if speed <= self.still_speed:
                if self._still_since is None:
                    self._still_since = t
                elif t - self._still_since >= self.still_s:
                    self._baseline = value
                    self._armed_at = t
            else:
                self._still_since = None
            return None

        if t - self._armed_at > self.max_t:
            self._baseline = None
            self._still_since = None
            return None
        change = value - self._baseline
        if change >= self.delta:
            self._wait_for_loss = True
            return "Hands_Spread"
        if change <= -self.delta:
            self._wait_for_loss = True
            return "Hands_Close"
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
                num_hands=2,
                # 기본 0.5는 책상 거리(팔 길이 밖) 작은 손을 자주 놓친다
                min_hand_detection_confidence=0.3,
                min_hand_presence_confidence=0.3,
                min_tracking_confidence=0.3,
            )
        )
        self._last_ts = 0
        self._closed = False

    def close(self):
        if not self._closed:
            self.recognizer.close()
            self._closed = True

    def hand(self, frame_bgr, ts_ms=None):
        hands = self.hands(frame_bgr, ts_ms)
        return hands[0] if hands else None

    def hands(self, frame_bgr, ts_ms=None):
        """Return up to two detected hands from a single MediaPipe inference."""
        import cv2

        if self._closed:
            raise RuntimeError("GestureEngine이 이미 닫혔습니다")
        if (frame_bgr is None or frame_bgr.ndim != 3 or frame_bgr.shape[2] != 3
                or 0 in frame_bgr.shape or frame_bgr.dtype != np.uint8):
            raise ValueError("잘못된 프레임입니다 (BGR uint8, HxWx3 배열이어야 합니다)")
        if ts_ms is None:
            ts_ms = int(time.monotonic() * 1000)
        ts_ms = max(ts_ms, self._last_ts + 1)
        self._last_ts = ts_ms
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        try:
            return parse_hands(self.recognizer.recognize_for_video(img, ts_ms))
        except Exception as e:
            # MediaPipe 제스처 그래프가 간헐적으로 "Packet isn't the sole owner" 등으로 죽는다.
            # 한 프레임 실패가 앱 전체(캘리브·음성 포함)를 내리면 안 되니 그 프레임만 버린다.
            print(f"[제스처 추론 오류, 프레임 건너뜀] {type(e).__name__}: {str(e)[:80]}")
            return []
