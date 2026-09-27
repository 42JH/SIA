"""회전과 모으기의 분리 및 진단 저장 회귀 검사."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from custom_motion import (CustomGestureStore, empty_templates, encode_sequence,
                           motion_comparison, template_bytes)
from gesture_be import GestureRegistration, GestureTemplateCache
import test_custom_motion as fixtures


def pair(t, twist=False):
    result = []
    for side, sign in [('Left', -1), ('Right', 1)]:
        hand = fixtures.hand(0, side)
        local = hand['landmarks'] - hand['landmarks'][0]
        angle = sign * t * 0.95 if twist else 0
        rot = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        # 두 동작 모두 조금 모이지만 비틀기에는 손목 회전이 추가된다.
        hand['landmarks'] = local @ rot.T + [0.5 + sign * (0.10 - t*0.01), 0.6]
        hand['gesture'] = None
        result.append(hand)
    return result


class MotionFeatureTests(unittest.TestCase):
    def seq(self, twist):
        ts = np.linspace(0, 1, 41)
        return encode_sequence(ts, [np.array([h['landmarks'] for h in pair(t, twist)]) for t in ts])

    def test_twist_not_diluted_by_landmark_average(self):
        a, b = self.seq(False), self.seq(True)
        parts = motion_comparison(a, b, 2)
        self.assertLess(parts['landmark'], 0.45)  # 이전 평균 거리로는 중복 거절되는 예
        self.assertGreater(parts['rotation'], 0.45)
        self.assertGreater(parts['score'], parts['landmark'])
        self.assertGreater(parts['score'], 0.45)
        self.assertLess(motion_comparison(a, a, 2)['score'], 1e-6)

    def test_registration_and_runtime_distinguish_motion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = empty_templates()
            data.update(sequences=np.array([self.seq(False)]), sequence_names=np.array(['gather']),
                        motions=np.array(['DYNAMIC']), hand_counts=np.array([2]), durations=np.array([1.0]))
            path = root/'templates.npz'
            path.write_bytes(template_bytes(data))
            store = CustomGestureStore(path)
            self.assertGreater(store.nearest_sequence(self.seq(True), 'DYNAMIC', 2)[0], 0.45)
            events = [store.update(pair(float(t), True), float(t))[1] for t in np.linspace(0, 1.2, 49)]
            self.assertFalse(any(events))
            store.reset_motion()
            events = [store.update(pair(min(float(t), 1), False), float(t))[1] for t in np.linspace(0, 1.2, 49)]
            self.assertIn('gather', events)

    def test_diagnostic_saves_rejected_capture_and_comparisons(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = empty_templates()
            data.update(sequences=np.array([self.seq(True)]), sequence_names=np.array(['twist']),
                        motions=np.array(['DYNAMIC']), hand_counts=np.array([2]), durations=np.array([1.0]))
            p=root/'store.npz'; p.write_bytes(template_bytes(data))
            link = fixtures.Link()
            reg = GestureRegistration(link, GestureTemplateCache(root/'cache', root/'combined.npz'), CustomGestureStore(p))
            with contextlib.redirect_stdout(io.StringIO()):
                reg.start(dict(tempId='diagnostic', motion='DYNAMIC', takes=1), now=0)
                for t in np.linspace(0, 1, 41):
                    reg._collect(pair(t, True), float(t))
                reg.phase='WAIT_FINISH'
                reg.finish()
            self.assertEqual(link.sent[-1][0], 'reg_rejected')
            saved=list((root/'logs'/'gesture_registration').glob('*.npz'))
            self.assertEqual(len(saved), 1)
            with np.load(saved[0], allow_pickle=False) as archive:
                meta=json.loads(str(archive['metadata']))
                self.assertEqual(meta['outcome'], 'rejected')
                self.assertEqual(archive['landmarks'].shape, (82,21,2))
                self.assertEqual(archive['frames'].shape, (41,4))
                self.assertIn('rotation', meta['comparisons'][0]['candidates'][0])
                np.testing.assert_array_equal(archive['reference_sequences'], data['sequences'])
            self.assertFalse(reg.active)

    def test_diagnostic_io_failure_does_not_change_registration_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); link=fixtures.Link()
            reg=GestureRegistration(link, GestureTemplateCache(root/'cache',root/'combined.npz'),CustomGestureStore(root/'missing.npz'))
            with contextlib.redirect_stdout(io.StringIO()), patch('gesture_be.save_registration_diagnostic',side_effect=OSError('disk full')):
                reg.start(dict(tempId='io',motion='DYNAMIC',takes=1),now=0)
                reg.phase='WAIT_FINISH'
                reg.finish()
            self.assertEqual(link.sent[-1][0],'reg_rejected')
            self.assertIn('손이 감지되지',link.sent[-1][1]['reason'])
            self.assertFalse(reg.active)


if __name__ == '__main__':
    unittest.main()
