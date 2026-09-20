"""Precise outlier feedback and partial-path swipe diagnostics."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from custom_motion import CustomGestureStore, encode_sequence
from gesture_be import GestureRegistration, GestureTemplateCache
from test_custom_motion import Link, hand
from test_registration_runtime_consistency import frames


class RegistrationConflictFeedbackTests(unittest.TestCase):
    def test_curve_claims_require_completion_and_exclude_query_take(self):
        for completes in (False, True):
            with self.subTest(completes=completes), tempfile.TemporaryDirectory() as tmp:
                store = CustomGestureStore(Path(tmp)/'missing.npz')
                reg = GestureRegistration(None, None, store)
                reg.take_frames = {2: [(float(i), [hand()]) for i in range(4)]}
                sequences = np.zeros((3, 24, 2, 21, 2), dtype=np.float32)
                sequences[1] = 99  # The query take must never be its own reference.
                original_data = store.data
                store.history.append((123, None, None))

                def update(runtime, hands, t):
                    self.assertEqual(len(runtime.data['sequences']), 2)
                    self.assertFalse(np.any(runtime.data['sequences'] == 99))
                    event = 'registration-peer' if completes and t == 2 else None
                    return None, event, True, None

                with patch.object(CustomGestureStore, 'update', update):
                    claims = reg._curve_runtime_claims(2, sequences, [1, 1, 1])
                self.assertEqual(claims, {0., 1., 2.} if completes else set())
                self.assertIs(store.data, original_data)
                self.assertEqual(store.history[0][0], 123)

    def test_single_take_cannot_exempt_a_curve_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            reg = GestureRegistration(None, None, CustomGestureStore(Path(tmp)/'missing.npz'))
            self.assertEqual(reg._curve_runtime_claims(1, [None], [1]), set())

    def test_missing_hand_frame_resets_builtin_detector(self):
        observed = []

        class Detector:
            def update(self, anchor, t, size=None):
                observed.append((t, anchor is None))
                return None

        reg = GestureRegistration(None, None, None)
        reg.takes = 1
        reg.take_frames = {1: [(float(t), [] if i == 10 else [hand()])
                              for i, t in enumerate(np.linspace(0, 1, 21))]}
        reg.BUILTIN_DYNAMIC_DETECTORS = (('swipe', Detector, lambda h: h['landmarks'][9]),)
        reg._builtin_dynamic_collision(1)
        self.assertIn((.5, True), observed)

    def test_outlier_reason_precedes_ambiguous_custom_duplicate_vote(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            link = Link()
            reg = GestureRegistration(link, GestureTemplateCache(root/'cache', root/'all.npz'),
                                      CustomGestureStore(root/'missing.npz'))
            with contextlib.redirect_stdout(io.StringIO()), patch(
                    'gesture_be.save_registration_diagnostic', return_value=None):
                reg.start(dict(tempId='outlier', motion='DYNAMIC', takes=3), now=0)
                for take in range(1, 4):
                    reg.take = take
                    for t, hs in frames(reverse=take == 1, hands=2):
                        reg._collect(hs, take * 4 + t)
                reg.phase = 'WAIT_FINISH'
                with patch.object(reg, '_validate_custom_collision_votes',
                                  side_effect=ValueError('ambiguous duplicate')) as vote:
                    reg.finish()
                    vote.assert_not_called()
            self.assertEqual(link.sent[-1][0], 'reg_rejected')
            self.assertIn('1회차 동작이 다른 회차와 다릅니다', link.sent[-1][1]['reason'])
            self.assertNotIn('similarTo', link.sent[-1][1])
            self.assertIsNone(link.payload)

    def test_partial_path_diagnostic_does_not_suppress_swipe(self):
        class Detector:
            def update(self, anchor, t, size=None):
                return 'Swipe_Right' if t >= .5 else None

        for curved in (False, True):
            with self.subTest(curved=curved):
                reg = GestureRegistration(None, None, None)
                reg.takes = 1
                source = []
                for t in np.linspace(0, 1, 21):
                    h = hand(.3 + (.08 * np.cos(2*np.pi*t) if curved else .2*t))
                    if curved:
                        h['landmarks'][:, 1] += .08*np.sin(2*np.pi*t)
                    source.append((float(t), [h]))
                reg.take_frames = {1: source}
                seq = encode_sequence([t for t, _ in source],
                                      [np.array([hs[0]['landmarks']]) for _, hs in source])
                reg.BUILTIN_DYNAMIC_DETECTORS = (('swipe', Detector, lambda h: h['landmarks'][9]),)
                with contextlib.redirect_stdout(io.StringIO()):
                    _, event, _ = reg._builtin_dynamic_collision(1, take_sequences=[seq])
                self.assertEqual(event, 'Swipe_Right')
                record = reg.builtin_collision_diagnostics[-1]
                self.assertEqual(record['take'], 1)
                self.assertAlmostEqual(record['elapsed_s'], .5)
                self.assertEqual(record['path_type'], 'PARTIAL_PATH' if curved else 'SWIPE_OR_UNKNOWN')


if __name__ == '__main__':
    unittest.main()
