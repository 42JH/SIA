"""기본 동작 분류 빈도를 유사도로 표시하는 등록 경로 회귀 검사."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from custom_motion import CustomGestureStore
from gesture_be import BUILTIN_POSE_REFERENCES, GestureRegistration, GestureTemplateCache
from gesture_diagnostics import save_registration_diagnostic
from test_custom_motion import Link, hand


class BuiltinFeedbackTests(unittest.TestCase):
    @staticmethod
    def _register_pose(landmarks, label='Victory'):
        root = Path(tempfile.mkdtemp())
        link = Link()
        reg = GestureRegistration(link, GestureTemplateCache(root / 'cache', root / 'all.npz'),
                                  CustomGestureStore(root / 'missing.npz'))
        reg.start(dict(tempId='t1', motion='STATIC', takes=3), now=0)
        for take in range(1, 4):
            reg.take = take
            for t in np.linspace(0, 0.35, 21):
                reg._collect([dict(landmarks=landmarks, handedness='Left', gesture=label)], take * 3 + t)
        reg.phase = 'WAIT_FINISH'
        reg.finish()
        return link.sent[-1][1]

    def test_victory_similarity_drops_when_finger_bends(self):
        """분류 일치율(항상 몇 %)이 아니라 실제 손모양 거리 기반 유사도라,
        분류 라벨은 여전히 Victory라도 검지를 살짝 굽히면 유사도가 뚜렷이
        낮아져야 한다 — 안 그러면 유사도가 항상 100%로 뜨는 문제가 그대로다."""
        reference = BUILTIN_POSE_REFERENCES['Victory']
        perfect = self._register_pose(reference.copy())
        bent = reference.copy()
        wrist, tip = bent[0], bent[8].copy()
        bent[8] = wrist + (tip - wrist) * 0.55  # 검지를 손목 쪽으로 절반 가까이 접음
        bent_result = self._register_pose(bent)

        self.assertGreater(perfect['similarity'], 0.9)
        self.assertLess(bent_result['similarity'], 0.6)
        self.assertLess(bent_result['similarity'], perfect['similarity'])

    def test_builtin_rejection_reports_classified_frame_ratio_as_similarity(self):
        # ILoveYou는 실제 촬영 기준 손모양이 없어(BUILTIN_POSE_REFERENCES에
        # 없음) 여전히 기존 방식(분류 일치율)을 쓴다.
        label = 'ILoveYou'
        with tempfile.TemporaryDirectory() as tmp:
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
            self.assertIn('너무 비슷합니다', payload['reason'])
            self.assertIsNone(link.payload)
            diagnostic, = (root / 'logs' / 'gesture_registration').glob('*.npz')
            with np.load(diagnostic, allow_pickle=False) as data:
                meta = json.loads(data['metadata'].item())
                self.assertEqual(meta['builtin_hits'], {label: 63})
                self.assertEqual(meta['sample_count'], 63)
                self.assertEqual(data['gestures'].tolist(), [label] * 63)
                np.testing.assert_allclose(data['gesture_scores'], 0.72)

    def test_builtin_rejection_with_reference_reports_geometric_similarity(self):
        """기준 손모양이 있는 라벨(BUILTIN_POSE_REFERENCES)은 분류 일치율이
        아니라 실제 손모양 거리 기반 유사도를 써야 한다 — 이 합성 손모양
        (hand())은 진짜 그 제스처가 아니므로 1.0이 나오면 안 된다."""
        for label in BUILTIN_POSE_REFERENCES:
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
                self.assertGreaterEqual(payload['similarity'], 0.0)
                self.assertLess(payload['similarity'], 1.0)
                self.assertIn('너무 비슷합니다', payload['reason'])

    def test_dominant_uncertainty_precedes_minor_builtin_label(self):
        """Mostly-unverified frames must not be named as a built-in collision."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            link = Link()
            reg = GestureRegistration(
                link, GestureTemplateCache(root / 'cache', root / 'all.npz'),
                CustomGestureStore(root / 'missing.npz'))
            reg.start(dict(tempId='uncertain', motion='STATIC', takes=3), now=0)
            for take in range(1, 4):
                reg.take = take
                for index, t in enumerate(np.linspace(0, 0.35, 21)):
                    observed = hand()
                    if index < 13:  # 62% uncertain
                        observed.update(gesture=None,
                                        pose_verification='unverified_finger_pose')
                    elif index < 18:  # 24% classified as one built-in pose
                        observed.update(gesture='Thumb_Up')
                    else:
                        observed.update(gesture=None)
                    reg._collect([observed], take * 3 + t)
            reg.phase = 'WAIT_FINISH'
            reg.finish()
            event, payload = link.sent[-1]
            self.assertEqual(event, 'reg_rejected')
            self.assertIn('손가락 모양을 정확히 확인하기 어렵습니다', payload['reason'])
            self.assertNotIn('similarTo', payload)

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
