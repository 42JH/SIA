"""실제 모델이 브이를 검지로 오분류한 좌표로 파서/등록/실행 경로를 검증한다."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

import numpy as np

from custom_motion import CustomGestureStore
from gesture_be import GestureRegistration, GestureTemplateCache
from gesture_pose import verified_finger_gesture
from hands import parse_hand, parse_hands, GestureStable, HoldToggle
from test_custom_motion import Link


CASES = {row['source']: row for row in json.loads(
    (Path(__file__).parent / 'testdata/builtin_finger_poses.json').read_text())['cases']}


def result_for(*names):
    rows = [CASES[name] for name in names]
    return NS(
        hand_landmarks=[[NS(x=x, y=y, z=z) for x, y, z in row['landmarks'][0]] for row in rows],
        hand_world_landmarks=[[NS(x=x, y=y, z=z) for x, y, z in row['world'][0]] for row in rows],
        gestures=[[NS(category_name=row['label'], score=row['score'])] for row in rows],
        handedness=[[NS(category_name='Left' if i == 0 else 'Right')] for i in range(len(rows))])


class FingerPoseTests(unittest.TestCase):
    def test_real_misclassification_is_corrected_in_both_parsers(self):
        self.assertEqual(CASES['peace_inverted']['label'], 'Pointing_Up')
        for hand in (parse_hand(result_for('peace_inverted')),
                     parse_hands(result_for('peace_inverted'))[0]):
            self.assertEqual(hand['gesture'], 'Victory')
            self.assertEqual(hand['model_gesture'], 'Pointing_Up')
            self.assertGreater(hand['model_score'], 0.7)
            self.assertIsNone(hand['score'])
            self.assertEqual(hand['pose_verification'], 'corrected_finger_pose')

    def test_correct_pointing_and_victory_are_preserved(self):
        for name, expected in [('one', 'Pointing_Up'), ('mute', 'Pointing_Up'), ('peace', 'Victory')]:
            h = parse_hand(result_for(name))
            self.assertEqual(h['gesture'], expected)
            self.assertEqual(h['score'], h['model_score'])

    def test_hand_order_does_not_mix_world_landmarks(self):
        for names in [('peace_inverted', 'one'), ('one', 'peace_inverted')]:
            hands = parse_hands(result_for(*names))
            self.assertEqual([h['gesture'] for h in hands],
                             ['Victory' if n == 'peace_inverted' else 'Pointing_Up' for n in names])

    def test_rotation_translation_scale_and_mirror_invariance(self):
        rng = np.random.default_rng(14)
        points = np.array(CASES['peace_inverted']['world'][0])
        for _ in range(80):
            rotation, _ = np.linalg.qr(rng.normal(size=(3, 3)))
            for mirror in (-1, 1):
                transformed = points @ rotation * [mirror, 1, 1]
                transformed = transformed * rng.uniform(.2, 4) + rng.normal(size=3)
                self.assertEqual(verified_finger_gesture('Pointing_Up', transformed)[0], 'Victory')

    def test_inverse_confusion_is_corrected(self):
        self.assertEqual(verified_finger_gesture('Victory', CASES['one']['world'][0])[0], 'Pointing_Up')

    def test_other_shapes_are_not_forced_into_victory_or_pointing(self):
        for name in ('rock', 'two_up', 'two_up_inverted', 'middle_finger', 'three2'):
            for label in ('Pointing_Up', 'Victory'):
                with self.subTest(name=name, label=label):
                    self.assertEqual(verified_finger_gesture(label, CASES[name]['world'][0])[0], 'None')
        # 다른 기본/커스텀 라벨은 임의로 바꾸지 않는다.
        for label in ('ILoveYou', 'custom'):
            self.assertEqual(verified_finger_gesture(label, CASES['peace_inverted']['world'][0])[0], label)
        # None일 때도 벌어짐이 뚜렷한 브이는 기본 중복 검사를 빠져나가면 안 된다.
        self.assertEqual(verified_finger_gesture('None', CASES['peace_inverted']['world'][0])[0], 'Victory')
        for name in ('rock', 'two_up', 'two_up_inverted', 'middle_finger', 'three2'):
            self.assertEqual(verified_finger_gesture('None', CASES[name]['world'][0])[0], 'None')

    def test_fist_is_verified_and_preserved(self):
        self.assertEqual(CASES['fist']['label'], 'Closed_Fist')
        h = parse_hand(result_for('fist'))
        self.assertEqual(h['gesture'], 'Closed_Fist')
        self.assertEqual(h['score'], h['model_score'])
        self.assertEqual(h['pose_verification'], 'verified_finger_pose')

    def test_none_recovers_to_fist_only_with_clear_evidence(self):
        self.assertEqual(verified_finger_gesture('None', CASES['fist']['world'][0]),
                         ('Closed_Fist', 'corrected_finger_pose'))
        # 손가락은 접혔어도 엄지가 뻗은 동작(엄지척·전화)이나, 애매한(그립)
        # 모양은 주먹으로 복구하면 안 된다.
        for name in ('call', 'grip', 'like', 'dislike'):
            with self.subTest(name=name):
                self.assertEqual(verified_finger_gesture('None', CASES[name]['world'][0])[0], 'None')

    def test_fist_claim_rejected_when_geometry_contradicts(self):
        # 손가락이 뚜렷이 펴져 있거나(palm 등) 엄지가 뻗어 있으면(dislike) 모순으로
        # 거절한다. 일부 손가락이 애매한 경우(like)는 판정을 보류한다 — 둘 다
        # 사용자에게 '주먹'으로 확정해 알리지 않는다는 점은 같다.
        for name in ('palm', 'dislike', 'one', 'peace'):
            with self.subTest(name=name):
                self.assertEqual(verified_finger_gesture('Closed_Fist', CASES[name]['world'][0]),
                                 ('None', 'incompatible_finger_pose'))
        self.assertEqual(verified_finger_gesture('Closed_Fist', CASES['like']['world'][0]),
                         ('None', 'unverified_finger_pose'))

    def test_thumb_and_other_builtin_labels_unaffected_by_fist_check(self):
        for name, label in [('like', 'Thumb_Up'), ('dislike', 'Thumb_Down')]:
            h = parse_hand(result_for(name))
            self.assertEqual(h['gesture'], label)
            self.assertEqual(h['score'], h['model_score'])
        for label in ('ILoveYou', 'custom'):
            self.assertEqual(verified_finger_gesture(label, CASES['fist']['world'][0])[0], label)

    def test_palm_is_verified_and_preserved(self):
        self.assertEqual(CASES['palm']['label'], 'Open_Palm')
        h = parse_hand(result_for('palm'))
        self.assertEqual(h['gesture'], 'Open_Palm')
        self.assertEqual(h['score'], h['model_score'])
        self.assertEqual(h['pose_verification'], 'verified_finger_pose')

    def test_none_recovers_to_palm_only_with_clear_evidence(self):
        self.assertEqual(verified_finger_gesture('None', CASES['palm']['world'][0]),
                         ('Open_Palm', 'corrected_finger_pose'))
        # 네 손가락은 펴져 있어도 엄지를 손목 쪽으로 접어 넣은 '네 손가락'
        # 모양은 손바닥 펴기로 복구하면 안 된다.
        self.assertEqual(verified_finger_gesture('None', CASES['four']['world'][0])[0], 'None')

    def test_palm_claim_rejected_when_geometry_contradicts(self):
        for name in ('fist', 'four', 'one', 'peace'):
            with self.subTest(name=name):
                self.assertEqual(verified_finger_gesture('Open_Palm', CASES[name]['world'][0]),
                                 ('None', 'incompatible_finger_pose'))

    def test_fist_and_palm_labels_do_not_interfere_with_each_other(self):
        self.assertEqual(verified_finger_gesture('Open_Palm', CASES['fist']['world'][0]),
                         ('None', 'incompatible_finger_pose'))
        self.assertEqual(verified_finger_gesture('Closed_Fist', CASES['palm']['world'][0]),
                         ('None', 'incompatible_finger_pose'))
        for label in ('ILoveYou', 'custom'):
            self.assertEqual(verified_finger_gesture(label, CASES['palm']['world'][0])[0], label)

    def test_registration_names_fist_and_preserves_raw_evidence(self):
        h = parse_hand(result_for('fist'))
        payload, saved = self.register([h] * 20)
        self.assertEqual(payload['similarTo'], 'Closed_Fist')
        self.assertEqual(set(saved['gestures']), {'Closed_Fist'})
        self.assertEqual(set(saved['model_gestures']), {'Closed_Fist'})

    def test_missing_degenerate_and_nonfinite_geometry_abstains(self):
        for points in (None, [], np.zeros((21, 3)), np.zeros((21, 2)),
                       np.full((21, 3), np.nan), np.full((21, 3), np.inf)):
            self.assertEqual(verified_finger_gesture('Pointing_Up', points),
                             ('None', 'unverified_finger_pose'))
        r = result_for('peace_inverted')
        r.hand_world_landmarks = []
        self.assertEqual(parse_hand(r)['gesture'], 'None')
        self.assertIsNone(parse_hand(result_for()))

    def test_execution_stabilizer_never_fires_pointing_for_reproduced_victory(self):
        stable = GestureStable(min_frames=3)
        toggles = {name: HoldToggle(hold_s=.7, cooldown_s=2) for name in ('Victory', 'Pointing_Up')}
        events = []
        for t in np.linspace(0, 1.5, 46):
            label = stable.update(parse_hand(result_for('peace_inverted'))['gesture'], float(t))
            events.extend(name for name, toggle in toggles.items() if toggle.update(name == label, float(t)))
        self.assertEqual(events, ['Victory'])

    def register(self, observations):
        with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):
            root = Path(tmp)
            link = Link()
            reg = GestureRegistration(link, GestureTemplateCache(root/'cache', root/'all.npz'),
                                      CustomGestureStore(root/'missing.npz'))
            reg.start(dict(tempId='pose', motion='STATIC', takes=3), now=0)
            for take in range(1, 4):
                reg.take = take
                for i, hand in enumerate(observations):
                    reg._collect([hand], take*3 + i*.02)
            reg.phase = 'WAIT_FINISH'
            reg.finish()
            self.assertIsNone(link.payload)
            event, payload = link.sent[-1]
            self.assertEqual(event, 'reg_rejected')
            diagnostic, = (root/'logs/gesture_registration').glob('*.npz')
            with np.load(diagnostic, allow_pickle=False) as data:
                saved = {k: data[k].copy() for k in ('gestures', 'model_gestures', 'model_scores',
                                                   'gesture_scores', 'world_landmarks')}
            return payload, saved

    def test_registration_names_victory_and_preserves_raw_evidence(self):
        h = parse_hand(result_for('peace_inverted'))
        payload, saved = self.register([h]*20)
        self.assertEqual(payload['similarTo'], 'Victory')
        self.assertEqual(payload['similarity'], 1.0)
        self.assertEqual(set(saved['gestures']), {'Victory'})
        self.assertEqual(set(saved['model_gestures']), {'Pointing_Up'})
        self.assertTrue(np.isnan(saved['gesture_scores']).all())
        self.assertTrue(np.isfinite(saved['world_landmarks']).all())

    def test_registration_chooses_most_frequent_not_first_seen(self):
        h = parse_hand(result_for('peace'))
        # 같은 좌표로 집계만 격리한다. 촬영 초반 25% 오인식이 안내를 선점하면 안 된다.
        wrong = dict(h, gesture='Pointing_Up')
        for samples in ([wrong]*5 + [h]*15, [h]*15 + [wrong]*5):
            payload, _ = self.register(samples)
            self.assertEqual(payload['similarTo'], 'Victory')

    def test_registration_tie_does_not_name_arbitrary_gesture(self):
        h = parse_hand(result_for('peace'))
        payload, _ = self.register([dict(h, gesture='Pointing_Up')]*10 + [h]*10)
        self.assertNotIn('similarTo', payload)
        self.assertIn('여러 기본 제스처', payload['reason'])

    def test_uncertain_geometry_does_not_silently_register_as_custom(self):
        r = result_for('peace_inverted')
        r.hand_world_landmarks = []
        payload, _ = self.register([parse_hand(r)]*20)
        self.assertNotIn('similarTo', payload)
        self.assertIn('명확히 확인하지 못했습니다', payload['reason'])


if __name__ == '__main__':
    unittest.main()
