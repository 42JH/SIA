"""공개 사진 좌표를 이용한 여러 커스텀 등록/저장/중복/인식 검사."""
import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np

from custom_motion import CustomGestureStore, read_templates, template_bytes
from evaluate_custom_registration import register
from hands import normalize_landmarks, parse_hand
from gesture_be import GestureRegistration


POSES = {r['source']: r for r in json.loads(
    (Path(__file__).parent/'testdata/custom_registration_poses.json').read_text())['cases']}


def observed(name):
    r = POSES[name]
    return parse_hand(NS(
        gestures=[[NS(category_name=r['label'], score=r['score'])]],
        hand_landmarks=[[NS(x=x, y=y, z=z) for x, y, z in r['landmarks'][0]]],
        hand_world_landmarks=[[NS(x=x, y=y, z=z) for x, y, z in r['world'][0]]],
        handedness=[[NS(category_name='Left')]]))


def hand(name, center=(.5, .6), side='Left'):
    h = observed(name)
    points = normalize_landmarks(h['landmarks']).reshape(21, 2) * .10
    if side == 'Right':
        points[:, 0] *= -1
    return dict(h, landmarks=points + center, handedness=side)


def takes_for(make, motion):
    return [[(float(p)*duration, make(float(p), i)) for p in np.linspace(0, 1, 31)]
            for i, duration in enumerate((.4, .4, .4) if motion == 'STATIC' else (.8, 1., 1.2))]


def scenarios():
    cases = []
    for name in ('four', 'grip', 'rock', 'pinkie'):
        cases.append((name, 'STATIC', takes_for(lambda p, i, n=name: [hand(n)], 'STATIC')))
    for name, first, second in [('pair_four_grip', 'four', 'grip'), ('pair_rock_pinkie', 'rock', 'pinkie')]:
        cases.append((name, 'STATIC', takes_for(
            lambda p, i, a=first, b=second: [hand(a, (.3, .6)), hand(b, (.7, .6), 'Right')], 'STATIC')))
    cases.append(('circle', 'DYNAMIC', takes_for(
        lambda p, i: [hand('three', (.5+.07*np.cos(2*np.pi*p), .6+.07*np.sin(2*np.pi*p)))], 'DYNAMIC')))
    cases.append(('vertical_tap', 'DYNAMIC', takes_for(
        lambda p, i: [hand('grabbing', (.5, .6-.10*np.sin(np.pi*p)))], 'DYNAMIC')))
    for name, sign in [('close_hands', -1), ('spread_hands', 1)]:
        cases.append((name, 'DYNAMIC', takes_for(
            lambda p, i, s=sign: [hand('grip', (.3-s*.1*p, .6)),
                                 hand('rock', (.7+s*.1*p, .6), 'Right')], 'DYNAMIC')))
    return cases


def batch_evaluation():
    rows, parts, accepted = [], [], []
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)/'combined.npz'
        for name, motion, takes in scenarios():
            result, payload = register(takes, motion, path)
            row = dict(name=name, motion=motion, hands=len(takes[0][0][1]), registration=result)
            rows.append(row)
            if payload is None:
                continue
            parts.append(read_templates(payload, name=name))
            path.write_bytes(template_bytes({k: np.concatenate([p[k] for p in parts]) for k in parts[0]}))
            duplicate, _ = register(takes, motion, path)
            row['duplicate'] = duplicate
            accepted.append((row, takes))
        for row, takes in accepted:
            store = CustomGestureStore(path)
            if row['motion'] == 'STATIC' and row['hands'] == 1:
                row['recognized'] = store.classify_with_distance(takes[1][0][1][0]['landmarks'])[0]
            else:
                events = []
                frames = takes[1] + [(1.+i/30, takes[1][-1][1]) for i in range(1, 10)]
                for t, hs in frames:
                    held, event, _, _ = store.update(hs, t)
                    name = event or held
                    if name and (not events or events[-1] != name):
                        events.append(name)
                row['recognized'] = events
    return rows


class CustomRegistrationBatchTests(unittest.TestCase):
    def test_consistency_accepts_an_actual_representative_within_threshold(self):
        reg = GestureRegistration(None, None, None)
        with contextlib.redirect_stdout(io.StringIO()):
            reg._validate_take_consistency([0., -.19, .20], lambda a, b: abs(a-b), .22)

    def test_consistency_rejects_outlier_and_disconnected_clusters(self):
        reg = GestureRegistration(None, None, None)
        for takes in ([0., .05, 1.], [0., .05, 1., 1.05]):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                reg._validate_take_consistency(takes, lambda a, b: abs(a-b), .22)

    def test_nonfinite_comparison_cannot_be_hidden_by_a_representative(self):
        reg = GestureRegistration(None, None, None)
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
            reg._validate_take_consistency([0, 1, 2], lambda a, b: np.nan if a == 1 else .1, .22)

    def test_telephone_shape_is_not_thumb_up(self):
        self.assertEqual(POSES['call']['label'], 'Thumb_Up')
        h = observed('call')
        self.assertEqual(h['gesture'], 'None')
        result, payload = register(takes_for(lambda p, i: [h], 'STATIC'), 'STATIC')
        self.assertEqual(result['event'], 'reg_captured', result)
        self.assertIsNotNone(payload)

    def test_real_thumbs_still_rejected_as_builtin(self):
        for name, label in [('like', 'Thumb_Up'), ('dislike', 'Thumb_Down')]:
            result, _ = register(takes_for(lambda p, i: [observed(name)], 'STATIC'), 'STATIC')
            self.assertEqual(result.get('similarTo'), label, result)

    def test_back_of_hand_victory_cannot_escape_builtin_check(self):
        self.assertEqual(POSES['peace_inverted']['label'], 'None')
        result, payload = register(takes_for(lambda p, i: [observed('peace_inverted')], 'STATIC'), 'STATIC')
        self.assertEqual(result.get('similarTo'), 'Victory', result)
        self.assertIsNone(payload)

    def test_fingers_together_remain_custom(self):
        for name in ('two_up', 'two_up_inverted'):
            result, payload = register(takes_for(lambda p, i: [observed(name)], 'STATIC'), 'STATIC')
            self.assertEqual(result['event'], 'reg_captured', result)
            self.assertIsNotNone(payload)

    def test_alternating_hands_same_static_pose(self):
        for name in ('four', 'rock', 'pinkie', 'grip'):
            takes = takes_for(lambda p, i: [hand(name, side='Right' if i == 1 else 'Left')], 'STATIC')
            result, payload = register(takes, 'STATIC')
            self.assertEqual(result['event'], 'reg_captured', result)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'pose.npz'
                path.write_bytes(payload)
                store = CustomGestureStore(path)
                for side in ('Left', 'Right'):
                    self.assertIsNotNone(store.classify_with_distance(hand(name, side=side)['landmarks'])[0])

    def test_different_pose_is_not_hidden_by_mirror_alignment(self):
        takes = takes_for(lambda p, i: [hand('four' if i == 0 else 'pinkie',
                                             side='Right' if i == 1 else 'Left')], 'STATIC')
        result, payload = register(takes, 'STATIC')
        self.assertEqual(result['event'], 'reg_rejected')
        self.assertIn('서로 다릅니다', result['reason'])
        self.assertIsNone(payload)

    def test_ten_gestures_registered_together_and_duplicates_rejected(self):
        for row in batch_evaluation():
            with self.subTest(name=row['name']):
                self.assertEqual(row['registration']['event'], 'reg_captured', row)
                self.assertEqual(row['duplicate']['event'], 'reg_rejected', row)
                self.assertEqual(row['duplicate'].get('similarTo'), row['name'], row)
                expected = row['name'] if row['hands'] == 1 and row['motion'] == 'STATIC' else [row['name']]
                self.assertEqual(row['recognized'], expected, row)


if __name__ == '__main__':
    unittest.main()
