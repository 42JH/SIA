"""회차 간 일관성: 실제 수집→검증→업로드/거부 경로 검사."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from custom_motion import CustomGestureStore
from gesture_be import GestureRegistration, GestureTemplateCache
from test_custom_motion import Link, hand


class TakeConsistencyTests(unittest.TestCase):
    def register(self, motion, count, different=False, missing=False, changed_count=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            link = Link()
            reg = GestureRegistration(link, GestureTemplateCache(root/'cache', root/'all.npz'),
                                      CustomGestureStore(root/'empty.npz'))
            with contextlib.redirect_stdout(io.StringIO()), patch(
                    'gesture_be.save_registration_diagnostic', return_value=None):
                reg.start(dict(tempId='consistency', motion=motion, takes=3), now=0)
                for take in range(1, 4):
                    reg.take = take
                    # 속도와 화면 내 시작 위치가 달라도 같은 동작은 통과해야 한다.
                    duration = (0.7, 1.0, 1.3)[take-1] if motion == 'DYNAMIC' else 0.4
                    for phase in np.linspace(0, 1, 31):
                        shape = 0.12 * phase if motion == 'DYNAMIC' else 0
                        if different and take == 3:
                            shape = 0.12 * (1-phase) if motion == 'DYNAMIC' else 0.12
                        n = 1 if changed_count and take == 3 else count
                        hands = [hand(0.25 + take*0.01 + side*0.3,
                                      'Left' if side == 0 else 'Right', shape=shape)
                                 for side in range(n)]
                        for h in hands:
                            h['gesture'] = None
                        reg._collect([] if missing and take == 3 else hands,
                                     take*4 + phase*duration)
                reg.phase = 'WAIT_FINISH'
                reg.finish()
            self.assertFalse(reg.active)
            return link

    def test_same_gesture_all_four_types(self):
        for motion in ('STATIC', 'DYNAMIC'):
            for count in (1, 2):
                with self.subTest(motion=motion, hands=count):
                    link = self.register(motion, count)
                    self.assertEqual(link.sent[-1][0], 'reg_captured', link.sent[-1])
                    self.assertIsNotNone(link.payload)

    def test_different_third_take_rejected_before_upload_all_four_types(self):
        for motion in ('STATIC', 'DYNAMIC'):
            for count in (1, 2):
                with self.subTest(motion=motion, hands=count):
                    link = self.register(motion, count, different=True)
                    event, data = link.sent[-1]
                    self.assertEqual(event, 'reg_rejected')
                    self.assertIn('회차', data['reason'])
                    self.assertTrue(
                        any(text in data['reason'] for text in
                            ('서로 다릅니다', '움직임 차이가 큽니다', '동작 방향이 반대입니다')),
                        data['reason'],
                    )
                    self.assertNotIn('similarTo', data)
                    self.assertIsNone(link.payload)

    def test_missing_static_take_cannot_use_other_takes_samples(self):
        link = self.register('STATIC', 1, missing=True)
        self.assertEqual(link.sent[-1][0], 'reg_rejected')
        self.assertIn('3회차', link.sent[-1][1]['reason'])
        self.assertIsNone(link.payload)

    def test_natural_dynamic_take_variance_is_allowed(self):
        """실측 정상 반복 범위에 해당하는 약 0.20의 동적 편차는 허용한다."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            link = Link()
            reg = GestureRegistration(link, GestureTemplateCache(root / 'cache', root / 'all.npz'),
                                      CustomGestureStore(root / 'empty.npz'))
            with contextlib.redirect_stdout(io.StringIO()), patch(
                    'gesture_be.save_registration_diagnostic', return_value=None):
                reg.start(dict(tempId='borderline', motion='DYNAMIC', takes=3), now=0)
                for take in range(1, 4):
                    reg.take = take
                    # take 3만 손모양 오프셋(0.05)을 더하면 회차 간 거리가 약
                    # 0.196이다. 기존 0.132에서는 정상 반복도 거부됐던 구간이다.
                    offset = 0.05 if take == 3 else 0.0
                    for phase in np.linspace(0, 1, 31):
                        h = dict(hand(0.3, 'Left', shape=0.12 * phase + offset), gesture=None)
                        reg._collect([h], take * 4 + phase)
                reg.phase = 'WAIT_FINISH'
                reg.finish()
            event, data = link.sent[-1]
            self.assertEqual(event, 'reg_captured', link.sent[-1])
            self.assertIsNotNone(link.payload)

    def test_hand_count_differs_between_takes(self):
        for motion in ('STATIC', 'DYNAMIC'):
            with self.subTest(motion=motion):
                link = self.register(motion, 2, changed_count=True)
                self.assertEqual(link.sent[-1][0], 'reg_rejected')
                self.assertIn('손 개수', link.sent[-1][1]['reason'])
                self.assertIsNone(link.payload)


if __name__ == '__main__':
    unittest.main()
