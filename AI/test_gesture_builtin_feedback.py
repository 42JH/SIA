"""기본 동작 분류 빈도를 유사도로 표시하는 등록 경로 회귀 검사."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from custom_motion import CustomGestureStore
from gesture_be import GestureRegistration, GestureTemplateCache
from gesture_diagnostics import save_registration_diagnostic
from test_custom_motion import Link, hand


class BuiltinFeedbackTests(unittest.TestCase):
    def test_builtin_rejection_reports_classified_frame_ratio_as_similarity(self):
        for label in ('Pointing_Up', 'Victory'):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                link = Link()
                reg = GestureRegistration(
                    link, GestureTemplateCache(root / 'cache', root / 'all.npz'),
                    CustomGestureStore(root / 'missing.npz'))
                reg.start(dict(tempId='builtin', motion='STATIC', takes=3), now=0)
                for take in range(1, 4):
                    reg.take = take
                    for t in np.linspace(0, 0.35, 21):
                        observed = hand()
                        observed.update(gesture=label, score=0.72)
                        reg._collect([observed], take * 3 + t)
                reg.phase = 'WAIT_FINISH'
                reg.finish()
                event, payload = link.sent[-1]
                self.assertEqual(event, 'reg_rejected')
                self.assertEqual(payload['similarTo'], label)
                # 프레임 전부가 그 라벨로 분류됐으니 비율 기반 유사도는 1.0.
                self.assertEqual(payload['similarity'], 1.0)
                self.assertIn('로 인식되었습니다', payload['reason'])
                self.assertIsNone(link.payload)
                diagnostic, = (root / 'logs' / 'gesture_registration').glob('*.npz')
                with np.load(diagnostic, allow_pickle=False) as data:
                    meta = json.loads(data['metadata'].item())
                    self.assertEqual(meta['builtin_hits'], {label: 63})
                    self.assertEqual(meta['sample_count'], 63)
                    self.assertEqual(data['gestures'].tolist(), [label] * 63)
                    np.testing.assert_allclose(data['gesture_scores'], 0.72)

    def test_diagnostics_preserve_frame_hand_order_and_missing_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = hand(), hand(0.6, 'Right')
            first.update(gesture='Victory', score=0.81)
            second.update(gesture=None)
            reg = SimpleNamespace(
                cache=SimpleNamespace(cache_dir=Path(tmp) / 'cache'),
                take_frames={1: [(0, []), (0.1, [second, first])]},
                temp_id='order', motion='STATIC', COLLISION_DIST=0.1,
                comparison_diagnostics=[], builtin_hits={}, samples=[],
                custom_store=SimpleNamespace(data={}))
            path = save_registration_diagnostic(reg, 'rejected', 'test')
            with np.load(path, allow_pickle=False) as data:
                self.assertEqual(data['frames'][:, 3].tolist(), [0, 2])
                self.assertEqual(data['handedness'].tolist(), ['Right', 'Left'])
                self.assertEqual(data['gestures'].tolist(), ['None', 'Victory'])
                self.assertTrue(np.isnan(data['gesture_scores'][0]))
                self.assertAlmostEqual(float(data['gesture_scores'][1]), 0.81)


if __name__ == '__main__':
    unittest.main()
