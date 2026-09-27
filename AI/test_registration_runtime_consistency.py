"""Runtime threshold, outlier diagnosis and real registration rejection path."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from custom_motion import CustomGestureStore, MATCH_DISTANCE, encode_sequence, read_templates, template_bytes
from gesture_be import GestureRegistration, GestureTemplateCache
from gesture_consistency import evaluate_dynamic_takes
from test_custom_motion import Link, hand


def frames(offset=0., reverse=False, hands=1):
    return [(float(t), [dict(hand(.3 + side * .3, 'Left' if side == 0 else 'Right',
                                  shape=.12 * (1 - t if reverse else t) + offset),
                             gesture=None) for side in range(hands)])
            for t in np.linspace(0, 1, 31)]


def sequence(offset=0., reverse=False, hands=1):
    source = frames(offset, reverse, hands)
    return encode_sequence([t for t, _ in source],
                           [np.array([h['landmarks'] for h in hs]) for _, hs in source])


class RuntimeConsistencyTests(unittest.TestCase):
    def test_recapture_excludes_only_target_and_preserves_original_store(self):
        from evaluate_custom_registration import register
        _, payload = register([frames()] * 3, 'DYNAMIC')
        self.assertIsNotNone(payload)
        target = read_templates(payload, name='target')
        competitor = read_templates(payload, name='competitor')
        for replace_name, with_competitor, expected in (
                (None, False, 'reg_rejected'),
                ('target', False, 'reg_captured'),
                ('target', True, 'reg_rejected'),
                ('unknown', False, 'reg_rejected')):
            with self.subTest(replace=replace_name, competitor=with_competitor), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                data = ({k: np.concatenate([target[k], competitor[k]]) for k in target}
                        if with_competitor else target)
                path = root / 'original.npz'
                path.write_bytes(template_bytes(data))
                original_bytes = path.read_bytes()
                store = CustomGestureStore(path)
                link = Link()
                reg = GestureRegistration(link, GestureTemplateCache(root / 'cache', root / 'all.npz'), store)
                with contextlib.redirect_stdout(io.StringIO()):
                    reg.start(dict(tempId='recapture', motion='DYNAMIC', takes=3,
                                   replaceGestureName=replace_name), now=0)
                    for take in range(1, 4):
                        reg.take = take
                        for t, hs in frames():
                            reg._collect(hs, take * 4 + t)
                    reg.phase = 'WAIT_FINISH'
                    reg.finish()
                self.assertEqual(link.sent[-1][0], expected, link.sent[-1])
                if with_competitor:
                    self.assertEqual(link.sent[-1][1]['similarTo'], 'competitor')
                self.assertIs(reg.custom_store, store)
                self.assertIn('target', store.class_names())
                self.assertEqual(path.read_bytes(), original_bytes)
                self.assertIsNone(reg.replace_gesture_name)

    def test_normal_repeats_and_every_outlier_position(self):
        for hands in (1, 2):
            good, bad = sequence(hands=hands), sequence(reverse=True, hands=hands)
            self.assertTrue(evaluate_dynamic_takes([good] * 3, hands)['passed'])
            for index in range(3):
                with self.subTest(hands=hands, outlier=index + 1):
                    takes = [good] * 3
                    takes[index] = bad
                    report = evaluate_dynamic_takes(takes, hands)
                    self.assertFalse(report['passed'])
                    self.assertEqual(report['outlier_take'], index + 1)
                    self.assertEqual(len(report['pairs']), 6)

    def test_strict_runtime_boundary_and_nonfinite_scores(self):
        for score, passed in ((MATCH_DISTANCE - 1e-8, True),
                              (MATCH_DISTANCE, False), (MATCH_DISTANCE + 1e-8, False),
                              (float('nan'), False), (float('inf'), False)):
            with self.subTest(score=score), patch(
                    'gesture_consistency.motion_matching_distance', return_value=score):
                report = evaluate_dynamic_takes([0, 1, 2], 1)
                self.assertEqual(report['passed'], passed)
                json.dumps(report, allow_nan=False)

    def test_ambiguous_and_directional_failures_do_not_name_outlier(self):
        for scores in (np.ones((3, 3)), np.array([[0, .1, .5], [.4, 0, .5], [.5, .5, 0]])):
            with patch('gesture_consistency.motion_matching_distance',
                       side_effect=lambda a, b, _: scores[a, b]):
                report = evaluate_dynamic_takes([0, 1, 2], 1)
            self.assertFalse(report['passed'])
            self.assertIsNone(report['outlier_take'])

    def test_runtime_incompatible_variance_is_rejected_even_if_old_gate_allows(self):
        takes = [sequence(), sequence(), sequence(offset=.08)]
        reg = GestureRegistration(None, None, None)
        with contextlib.redirect_stdout(io.StringIO()):
            reg._validate_take_consistency(takes, lambda a, b: reg._dynamic_take_distance(a, b, 1),
                                           reg.TAKE_SEQUENCE_DISTANCE)
        report = evaluate_dynamic_takes(takes, 1)
        self.assertFalse(report['passed'])
        self.assertEqual(report['outlier_take'], 3)

    def test_existing_candidate_wins_tie_without_mutating_store(self):
        good = sequence()
        references = dict(sequences=[good], sequence_names=['existing'],
                          motions=['DYNAMIC'], hand_counts=[1])
        report = evaluate_dynamic_takes([good] * 3, 1, references)
        self.assertFalse(report['passed'])
        self.assertTrue(all(row['peer_match'] for row in report['takes']))
        self.assertTrue(all(row['competing_name'] == 'existing' for row in report['takes']))
        np.testing.assert_array_equal(references['sequences'][0], good)

    def test_missing_peer_is_not_self_match(self):
        for takes in ([], [sequence()]):
            self.assertFalse(evaluate_dynamic_takes(takes, 1)['passed'])

    def test_rejected_capture_has_one_result_no_upload_and_saved_diagnostics(self):
        for bad_take in (1, 2, 3):
            with self.subTest(bad_take=bad_take), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                link = Link()
                store = CustomGestureStore(root / 'missing.npz')
                reg = GestureRegistration(link, GestureTemplateCache(root / 'cache', root / 'all.npz'), store)
                with contextlib.redirect_stdout(io.StringIO()):
                    reg.start(dict(tempId='quality', motion='DYNAMIC', takes=3), now=0)
                    for take in range(1, 4):
                        reg.take = take
                        for t, hs in frames(reverse=take == bad_take):
                            reg._collect(hs, take * 4 + t)
                    reg.phase = 'WAIT_FINISH'
                    reg.finish()
                    reg.finish_for('quality')
                    reg.finish()
                finals = [(e, p) for e, p in link.sent if e in ('reg_rejected', 'reg_captured')]
                self.assertEqual(len(finals), 1)
                self.assertEqual(finals[0][0], 'reg_rejected')
                self.assertIn(f'{bad_take}회차 동작이 다른 회차와 다릅니다', finals[0][1]['reason'])
                self.assertNotIn('similarTo', finals[0][1])
                self.assertIsNone(link.payload)
                archives = list((root / 'logs' / 'gesture_registration').glob('*.npz'))
                self.assertEqual(len(archives), 1)
                with np.load(archives[0], allow_pickle=False) as archive:
                    report = json.loads(archive['metadata'].item())['take_consistency']
                self.assertEqual(report['outlier_take'], bad_take)
                self.assertGreater(report['elapsed_ms'], 0)
                # A corrected attempt must run all three takes again and may
                # upload only after the new complete set passes validation.
                with contextlib.redirect_stdout(io.StringIO()):
                    reg.start(dict(tempId='retry', motion='DYNAMIC', takes=3), now=0)
                    for take in range(1, 4):
                        reg.take = take
                        for t, hs in frames():
                            reg._collect(hs, take * 4 + t)
                    reg.phase = 'WAIT_FINISH'
                    reg.finish()
                self.assertEqual(link.sent[-1][0], 'reg_captured')
                self.assertIsNotNone(link.payload)


if __name__ == '__main__':
    unittest.main()
