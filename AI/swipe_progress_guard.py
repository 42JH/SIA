# -*- coding: utf-8 -*-
"""스와이프 "판정 기준에 다가가는 움직임"만 정적 홀드를 억제한다.

기존 두 방식의 공통 문제: "동적 동작 도중/직후엔 정적 홀드를 쉬게 한다"는 접근 자체가,
손을 들어 Open_Palm/Closed_Fist를 하려는 정상적인 움직임까지 "동작"으로 잡아 지연을
늘렸다(우리 방식 1.4초 고정창: 순수 Open_Palm 세션에서 지연 1.77→3.52초,
기본값 0.25초도 1.77→2.47초). 실측(다른 워크트리, 64구간)에서는 그 지연이 실제
재현율 손실(38/64→34/64)로도 나타났다.

이 가드는 "손이 조금이라도 빠르게 움직였는가"가 아니라, "스와이프 판정 기준(dist)의
일정 비율 이상을 이미 이동했는가"만 본다 — SwipeDetector 자신의 거리·수평비율 철학을
그대로 재사용하되 문턱만 낮춘다. 손을 들어 자세를 잡는 동작은 보통 수직 위주이거나
수평 이동량이 이 문턱에 못 미치므로 억제 대상에서 자연히 빠진다.
"""
from collections import deque

from hands import REFERENCE_PALM_SIZE


class SwipeProgressGuard:
    def __init__(self, dist=0.12, max_t=0.9, horizontal_ratio=1.0,
                 progress_fraction=0.5, settle_s=0.25):
        self.progress_dist = dist * progress_fraction
        self.max_t = max_t
        self.horizontal_ratio = horizontal_ratio
        self.settle_s = settle_s
        self.reset()

    def reset(self):
        self._hist = deque()
        self._input_scale = None
        self.blocked = False
        self.quiet_since = None

    def _unblock_after_settle(self, t):
        if self.quiet_since is None:
            self.quiet_since = t
        elif t - self.quiet_since >= self.settle_s:
            self.blocked = False

    def update(self, anchor, t, size=None, event=False):
        """anchor: (x, y) 또는 None(손 없음/추적 대상 아님). event: 이번 프레임에
        실제 동적 이벤트(스와이프 등)가 발동했는가 — 발동 직후는 무조건 억제."""
        if anchor is None:
            self._hist.clear()
            self._input_scale = None
            if event:
                self.blocked = True
                self.quiet_since = None
            elif self.blocked:
                self._unblock_after_settle(t)
            return self.blocked
        if size is not None:
            if self._input_scale is None:
                self._input_scale = REFERENCE_PALM_SIZE / max(float(size), 1e-6)
            x = float(anchor[0]) * self._input_scale
            y = float(anchor[1]) * self._input_scale
        else:
            x, y = float(anchor[0]), float(anchor[1])
        self._hist.append((t, x, y))
        while self._hist and t - self._hist[0][0] > self.max_t:
            self._hist.popleft()
        progressing = False
        for t0, x0, y0 in self._hist:
            dx, dy = x - x0, y - y0
            if abs(dx) >= self.progress_dist and abs(dy) < abs(dx) * self.horizontal_ratio:
                progressing = True
                break
        if event or progressing:
            self.blocked = True
            self.quiet_since = None
        elif self.blocked:
            self._unblock_after_settle(t)
        return self.blocked
