"""촬영 구간과 손 크기 변화 회귀 검사. 카메라/서버 없이 실행한다."""
import contextlib
import io
import unittest

import numpy as np

from custom_motion import encode_sequence, trim_motion_frames
from hands import SwipeDetector, SCREEN_SWIPE_CONFIG
from test_custom_motion import MotionTests, hand
from gesture_be import GestureRegistration


class BoundaryTests(unittest.TestCase):
    def test_size_change_alone_never_swipes(self):
        for end in (0.06, 0.08, 0.18):
            detector = SwipeDetector(**SCREEN_SWIPE_CONFIG)
            events = []
            for t in np.linspace(0, 1, 61):
                size = 0.12 + (end - 0.12) * np.clip((t - 0.5) / 0.3, 0, 1)
                events.append(detector.update((0.7, 0.2), t, size=size))
            self.assertFalse(any(events))

    def test_real_swipe_and_reset(self):
        detector = SwipeDetector(**SCREEN_SWIPE_CONFIG)
        for size in (0.06, 0.18):
            detector.update(None, 0)
            events = []
            for t in np.linspace(0, 1, 61):
                x = 0.3 + size * 2 * np.clip((t - 0.5) / 0.3, 0, 1)
                events.append(detector.update((x, 0.2), t, size=size))
            self.assertEqual([v for v in events if v], ["Swipe_Right"])

    def test_trim_preserves_middle_pause_and_return(self):
        frames = []
        for t in np.linspace(0, 2, 81):
            x = 0.3 + 0.1 * np.clip((t - 0.4) / 0.3, 0, 1)
            x -= 0.1 * np.clip((t - 1.0) / 0.3, 0, 1)
            frames.append((t, np.array([hand(x)["landmarks"]])))
        trimmed = trim_motion_frames(frames)
        self.assertAlmostEqual(trimmed[0][0], 0.4, delta=0.03)
        self.assertAlmostEqual(trimmed[-1][0], 1.3, delta=0.03)
        self.assertTrue(any(0.8 < t < 0.95 for t, _ in trimmed))


class RegistrationBoundaryTests(MotionTests):
    # 기존 fixture만 재사용하고 부모의 테스트는 아래 로더에서 중복 실행하지 않는다.
    def test_trimmed_duration_and_runtime(self):
        from custom_motion import CustomGestureStore
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="trim", motion="DYNAMIC", takes=3, takeDurationSec=2), now=0)
        def pose(t):
            return [hand(shape=0.10 * np.clip((t - 0.5) / 0.8, 0, 1))]
        for take in range(1, 4):
            reg.take = take
            for t in np.linspace(0, 2, 81):
                reg._collect(pose(t), take * 3 + t)
        reg.phase = "WAIT_FINISH"
        with contextlib.redirect_stdout(io.StringIO()) as log:
            reg.finish()
        self.assertEqual(self.link.sent[-1][0], "reg_captured", self.link.sent[-1])
        self.assertIn("nearest=", log.getvalue())
        self.cache.sync(self.link, [dict(id=1, name="trim", sha256="hash")])
        store = CustomGestureStore(self.cache.combined_path)
        self.assertLess(float(store.data["durations"][0]), 1.0)
        events = [store.update(pose(t), t)[1] for t in np.linspace(0, 2, 81)]
        self.assertIn("trim", events)
        old = encode_sequence(np.linspace(0, 2, 81), [np.array([pose(t)[0]["landmarks"]]) for t in np.linspace(0, 2, 81)])
        score, name = store.nearest_sequence(old, "DYNAMIC", 1)
        self.assertEqual(name, "trim")
        self.assertLess(score, reg.COLLISION_DIST)

    def test_collision_log_has_take_time_direction(self):
        from custom_motion import CustomGestureStore
        reg = GestureRegistration(self.link, self.cache, CustomGestureStore(self.root / "missing.npz"))
        reg.start(dict(tempId="log", motion="DYNAMIC", takes=1), now=0)
        for t in np.linspace(0, 1, 61):
            reg._collect([dict(hand(0.3 + 0.3 * np.clip((t - 0.5) / 0.3, 0, 1)), size=0.12)], t)
        with contextlib.redirect_stdout(io.StringIO()) as log:
            _, event, similarity = reg._builtin_dynamic_collision()
        self.assertEqual(event, "Swipe_Right")
        self.assertGreater(similarity, 0)
        for field in ("tempId=log", "take=1", "elapsed=", "direction=Swipe_Right"):
            self.assertIn(field, log.getvalue())


def load_tests(loader, tests, pattern):
    suite = loader.loadTestsFromTestCase(BoundaryTests)
    for name in ("test_trimmed_duration_and_runtime", "test_collision_log_has_take_time_direction"):
        suite.addTest(RegistrationBoundaryTests(name))
    return suite
