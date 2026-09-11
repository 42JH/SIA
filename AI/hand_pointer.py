"""손 커서 데모의 포인터 필터와 핀치 상태 머신."""
import math
import time

import numpy as np

PINCH_ON, PINCH_OFF = 0.35, 0.45


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
