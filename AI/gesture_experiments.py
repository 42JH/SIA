"""제스처 스튜디오 및 향후 실측을 위한 실험용 감지기."""
import collections
import math
import time


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

    def __init__(self, tip_dist=0.12, max_t=0.5,
                 still_speed=0.18, still_t=0.25):
        self.tip_dist = tip_dist
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
    """의도적인 양손 벌림/모음 동작을 한 번 감지한다.

    손바닥 중심 사이의 거리를 평균 손바닥 크기로 정규화하여,
    사용자와 카메라 사이의 거리에 따른 영향을 줄인다.
    한 번 발동한 뒤에는 양손이 화면에서 벗어나야 다시 감지할 준비를 한다.
    이를 통해 복귀 동작이 반대 명령으로 인식되는 것을 방지한다.
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
