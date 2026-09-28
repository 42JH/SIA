import unittest

from swipe_progress_guard import SwipeProgressGuard


class SwipeProgressGuardTests(unittest.TestCase):
    def test_vertical_hand_raise_does_not_block(self):
        """손을 들어 자세를 잡는 수직 위주 이동은 억제 대상이 아니다."""
        guard = SwipeProgressGuard()
        for i in range(30):
            t = i / 30
            y = 0.86 - 0.5 * (t / 1.0)
            blocked = guard.update((0.5, y), t, size=0.12)
            self.assertFalse(blocked, f"t={t} y={y}에서 잘못 차단됨")

    def test_small_jitter_does_not_block(self):
        guard = SwipeProgressGuard()
        for i in range(60):
            t = i / 30
            x = 0.5 + 0.01 * (-1) ** i
            self.assertFalse(guard.update((x, 0.5), t, size=0.12))

    def test_horizontal_progress_blocks(self):
        """실제로 스와이프 임계값의 절반 이상 수평 이동하면 차단한다."""
        guard = SwipeProgressGuard(dist=0.12, progress_fraction=0.5)
        blocked_at = None
        for i in range(30):
            t = i / 30
            x = 0.5 - 0.3 * (t / 1.0)  # 1초에 0.3만큼 왼쪽 이동
            blocked = guard.update((x, 0.5), t, size=0.12)
            if blocked and blocked_at is None:
                blocked_at = t
        self.assertIsNotNone(blocked_at)
        # 0.06(=0.12*0.5) 이동에 걸리는 시간 지점 근처에서 차단돼야 한다
        self.assertLess(blocked_at, 0.5)

    def test_recovers_after_settle(self):
        guard = SwipeProgressGuard(settle_s=0.25)
        guard.update((0.5, 0.5), 0, size=0.12, event=True)
        self.assertTrue(guard.blocked)
        self.assertTrue(guard.update((0.5, 0.5), 0.1, size=0.12))
        self.assertTrue(guard.update((0.5, 0.5), 0.2, size=0.12))
        self.assertFalse(guard.update((0.5, 0.5), 0.36, size=0.12))

    def test_event_forces_block_even_without_progress(self):
        guard = SwipeProgressGuard()
        self.assertTrue(guard.update((0.5, 0.5), 0, size=0.12, event=True))

    def test_missing_hand_does_not_invent_progress_but_keeps_block_until_settled(self):
        guard = SwipeProgressGuard(settle_s=0.25)
        guard.update((0.5, 0.5), 0, size=0.12, event=True)
        self.assertTrue(guard.update(None, 0.1))
        self.assertTrue(guard.update(None, 0.2))
        self.assertFalse(guard.update(None, 0.36))

    def test_reset_clears_state(self):
        guard = SwipeProgressGuard()
        guard.update((0.5, 0.5), 0, size=0.12, event=True)
        guard.reset()
        self.assertFalse(guard.blocked)
        self.assertFalse(guard.update((0.5, 0.5), 1, size=0.12))


if __name__ == "__main__":
    unittest.main()
