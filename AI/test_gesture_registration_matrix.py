"""다양한 FPS·촬영 모드·손 수에서 경계 판정 및 실제 등록 종료를 검사한다."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np

from custom_motion import CustomGestureStore
from gesture_be import GestureRegistration, GestureTemplateCache
import test_custom_motion as fixtures


class RegistrationMatrixTests(unittest.TestCase):
    def bounds(self, times, bad, missing=()):
        reg = GestureRegistration(None, None, None)
        reg.temp_id = 'matrix'
        reg.take_frames = {1: []}
        for i, t in enumerate(times):
            h = fixtures.hand()
            if i in bad:
                h['landmarks'][8, 0] = 1.04
            reg.take_frames[1].append((float(t), [] if i in missing else [h]))
        return reg

    def check_bounds(self, reg, rejected):
        with contextlib.redirect_stdout(io.StringIO()):
            if rejected:
                with self.assertRaises(ValueError):
                    reg._validate_frame_bounds()
            else:
                reg._validate_frame_bounds()

    def test_fps_mode_matrix(self):
        # 4 FPS × 2 촬영 길이 × 3 상태 = 24 시나리오.
        for fps in (10, 15, 30, 60):
            for duration in (0.4, 2.0):
                times = np.linspace(0, duration, round(fps * duration) + 1)
                for state, bad, rejected in (
                    ('clean', set(), False),
                    ('single_spike', {len(times)//2}, False),
                    ('always_out', set(range(len(times))), True),
                ):
                    with self.subTest(fps=fps, duration=duration, state=state):
                        self.check_bounds(self.bounds(times, bad), rejected)

    def test_coordinate_edges(self):
        for axis in (0, 1):
            for value, rejected in ((-0.02, False), (1.02, False), (-0.0201, True), (1.0201, True)):
                with self.subTest(axis=axis, value=value):
                    reg = self.bounds(np.linspace(0, 1, 31), set())
                    for _, hands in reg.take_frames[1]:
                        hands[0]['landmarks'][8, axis] = value
                    self.check_bounds(reg, rejected)

    def test_ratio_threshold(self):
        for count in (34, 35, 36):
            with self.subTest(outside=count):
                # 연속 이탈 없이 비율 조건만 검사한다.
                self.check_bounds(self.bounds(np.arange(100)/50, set(range(0, count*2, 2))), count >= 35)

    def test_duration_threshold(self):
        for duration, rejected in ((0.499, False), (0.5, True), (0.501, True)):
            with self.subTest(duration=duration):
                clipped_times = list(np.arange(0, duration, 0.05))
                if not clipped_times or clipped_times[-1] < duration:
                    clipped_times.append(duration)
                times = clipped_times + list(np.linspace(duration+0.03, 2, 28))
                self.check_bounds(
                    self.bounds(times, set(range(len(clipped_times)))), rejected)

    def test_missing_frames_do_not_dilute_ratio(self):
        # 검출 10프레임 중 2회 이탈, 나머지 미검출 90프레임으로 희석하지 않는다.
        self.check_bounds(self.bounds(np.arange(100)/50, {0, 9}, set(range(10, 100))), False)

    def test_failure_identifies_take(self):
        reg = self.bounds(np.arange(30)/30, set())
        reg.take_frames[2] = self.bounds(np.arange(30)/30+3, set(range(30))).take_frames[1]
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, '2회차'):
            reg._validate_frame_bounds()

    def test_registration_end_to_end(self):
        # STATIC/DYNAMIC × 1/2손 × 정상/순간 튐/지속 이탈 = 12 시나리오.
        for motion in ('STATIC', 'DYNAMIC'):
            for count in (1, 2):
                for state in ('clean', 'single_spike', 'always_out'):
                    with self.subTest(motion=motion, count=count, state=state), tempfile.TemporaryDirectory() as tmp:
                        root = Path(tmp)
                        link = fixtures.Link()
                        reg = GestureRegistration(link, GestureTemplateCache(root/'cache', root/'combined.npz'),
                                                  CustomGestureStore(root/'empty.npz'))
                        duration = 0.4 if motion == 'STATIC' else 2
                        with contextlib.redirect_stdout(io.StringIO()):
                            reg.start(dict(tempId='integration', motion=motion, takes=1), now=0)
                            times = np.linspace(0, duration, round(duration*30)+1)
                            for i, t in enumerate(times):
                                shape = 0.10 * np.clip((t-0.4)/0.8, 0, 1) if motion == 'DYNAMIC' else 0
                                hands = [fixtures.hand(0.35, shape=shape)]
                                if count == 2:
                                    hands.append(fixtures.hand(0.7, 'Right'))
                                for h in hands:
                                    h['gesture'] = None
                                # 같은 기준 자세에서 손끝 한 점만 2% 경계 주변에서 튄다.
                                hands[-1]['landmarks'][8, 0] = 1.01
                                if state == 'always_out' or (state == 'single_spike' and i == len(times)//2):
                                    hands[-1]['landmarks'][8, 0] = 1.04
                                reg._collect(hands, float(t))
                            reg.phase = 'WAIT_FINISH'
                            reg.finish()
                        event, payload = link.sent[-1]
                        if state == 'always_out':
                            self.assertEqual(event, 'reg_rejected', payload)
                            self.assertIn('손목과 손끝이 화면 안', payload['reason'])
                            self.assertNotIn('similarTo', payload)
                            self.assertIsNone(link.payload)
                        else:
                            self.assertEqual(event, 'reg_captured', payload)
                            self.assertIsNotNone(link.payload)
                        self.assertFalse(reg.active)


if __name__ == '__main__':
    unittest.main()
