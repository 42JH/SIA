"""한 손 좌우 호환, 화면 이동 방향 및 양손 역할 보존 회귀 검사."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np

from custom_motion import (CustomGestureStore, empty_templates, encode_sequence,
                           matching_distance, template_bytes)
from gesture_be import GestureRegistration, GestureTemplateCache
from hands import CustomGestures, normalize_landmarks
import test_custom_motion as fixtures


def opposite(points):
    result = np.array(points, copy=True)
    result[..., 0] = 2 * result[0, 0] - result[..., 0]
    return result


def pose(t, other=False, direction=1):
    h = fixtures.hand(0.4 + direction * 0.15 * t, shape=0.07 * t)
    if other:
        h['landmarks'] = opposite(h['landmarks'])
        h['handedness'] = 'Right'
    return h


class HandednessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'templates.npz'

    def make_store(self):
        times = np.linspace(0, 1, 41)
        seq = encode_sequence(times, [np.array([pose(t)['landmarks']]) for t in times])
        data = empty_templates()
        data.update(sequences=np.array([seq]), sequence_names=np.array(['move']),
                    motions=np.array(['DYNAMIC']), hand_counts=np.array([1]), durations=np.array([1.0]))
        self.path.write_bytes(template_bytes(data))
        return CustomGestureStore(self.path), seq

    def test_static_existing_template_matches_both_hands(self):
        store = CustomGestures(self.path)
        lm = pose(0.7)['landmarks']
        store.add('pose', [normalize_landmarks(lm)])
        original = self.path.read_bytes()
        store = CustomGestures(self.path)
        for points in (lm, opposite(lm)):
            self.assertEqual(store.classify(points), 'pose')
            name, score = store.classify_with_distance(points)
            self.assertEqual(name, 'pose')
            self.assertLess(score, 1e-6)
            name, score = store.nearest_class([normalize_landmarks(points)])
            self.assertEqual(name, 'pose')
            self.assertLess(score, 1e-6)
        self.assertEqual(self.path.read_bytes(), original)

    def test_dynamic_both_hands_and_prefix_match(self):
        store, seq = self.make_store()
        original = self.path.read_bytes()
        for other in (False, True):
            store.reset_motion()
            results = [store.update([pose(t, other)], float(t)) for t in np.linspace(0, 1.05, 43)]
            self.assertEqual([event for _, event, _, _ in results if event], ['move'])
            self.assertTrue(any(claimed and event is None for _, event, claimed, _ in results[:25]))
            times = np.linspace(0, 1, 41)
            candidate = encode_sequence(times, [np.array([pose(t, other)['landmarks']]) for t in times])
            score, name = store.nearest_sequence(candidate, 'DYNAMIC', 1)
            self.assertEqual(name, 'move')
            self.assertLess(score, 1e-5)
        self.assertEqual(self.path.read_bytes(), original)

    def test_mirror_does_not_reverse_motion_direction(self):
        store, seq = self.make_store()
        times = np.linspace(0, 1, 41)
        backwards = encode_sequence(times, [np.array([pose(t, True, -1)['landmarks']]) for t in times])
        self.assertGreater(matching_distance(backwards, seq, 1), 0.45)
        events = [store.update([pose(t, True, -1)], float(t))[1] for t in times]
        self.assertFalse(any(events))

    def test_two_hand_roles_are_not_mirrored(self):
        times = np.linspace(0, 1, 41)
        original = [np.array([pose(t)['landmarks'], fixtures.hand(0.8, 'Right')['landmarks']]) for t in times]
        changed = [np.array([opposite(p[0]), p[1]]) for p in original]
        a, b = encode_sequence(times, original), encode_sequence(times, changed)
        from custom_motion import distance
        self.assertEqual(matching_distance(a, b, 2), distance(a, b, 2))
        self.assertGreater(matching_distance(a, b, 2), 0.1)

    def test_registration_rejects_opposite_hand_duplicate(self):
        store, _ = self.make_store()
        link = fixtures.Link()
        cache = GestureTemplateCache(self.path.parent / 'cache', self.path.parent / 'combined.npz')
        reg = GestureRegistration(link, cache, store)
        with contextlib.redirect_stdout(io.StringIO()):
            reg.start(dict(tempId='opposite', motion='DYNAMIC', takes=1, takeDurationSec=1), now=0)
            for t in np.linspace(0, 1, 41):
                # 기본 스와이프 준비 조건과 분리해 커스텀 중복 경로를 검증한다.
                reg._collect([pose(t, True)], t * 0.3)
            reg.phase = 'WAIT_FINISH'
            reg.finish()
        event, payload = link.sent[-1]
        self.assertEqual(event, 'reg_rejected')
        self.assertEqual(payload['similarTo'], 'move')
        self.assertIsNone(link.payload)


if __name__ == '__main__':
    unittest.main()
