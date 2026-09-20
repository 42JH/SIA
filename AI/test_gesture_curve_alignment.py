"""Time alignment preserves path order, endpoints and finger-shape checks."""
import unittest
import tempfile
from pathlib import Path
import numpy as np
from custom_motion import (_align_curve, encode_sequence, motion_matching_distance,
                           MATCH_DISTANCE, CustomGestureStore, empty_templates)
from test_custom_motion import hand


def circle(power=1, reverse=False, shape=0, partial=1):
    times = np.linspace(0, 1, 81)
    points = []
    for t in times:
        angle = (t ** power) * 2*np.pi * partial * (-1 if reverse else 1)
        h = hand(.4 + .09*np.cos(angle), shape=shape)
        h['landmarks'][:, 1] += .09*np.sin(angle)
        points.append(np.array([h['landmarks']]))
    return encode_sequence(times, points)


def two_hand_motion(power=1, right_power=None, right_shape=0):
    times = np.linspace(0, 1, 81)
    points = []
    for t in times:
        left = t ** power
        right = t ** (right_power if right_power is not None else power)
        hs = [hand(.3 + .09*np.sin(2*np.pi*left)),
              hand(.7 - .09*np.sin(2*np.pi*right), side='Right', shape=right_shape)]
        hs[0]['landmarks'][:, 1] += .06*(1-np.cos(2*np.pi*left))
        hs[1]['landmarks'][:, 1] += .06*(1-np.cos(2*np.pi*right))
        points.append(np.array([h['landmarks'] for h in hs]))
    return encode_sequence(times, points)


class CurveAlignmentTests(unittest.TestCase):
    def test_two_hands_share_speed_alignment(self):
        self.assertLess(motion_matching_distance(two_hand_motion(), two_hand_motion(power=1.65), 2), MATCH_DISTANCE)

    def test_two_hand_relative_timing_is_preserved(self):
        self.assertGreaterEqual(motion_matching_distance(two_hand_motion(), two_hand_motion(right_power=2.5), 2), MATCH_DISTANCE)

    def test_two_hand_roles_are_not_swapped(self):
        seq = two_hand_motion()
        self.assertGreaterEqual(motion_matching_distance(seq, seq[:, ::-1], 2), MATCH_DISTANCE)

    def test_one_changed_hand_is_not_hidden_by_other_hand(self):
        self.assertGreaterEqual(motion_matching_distance(two_hand_motion(), two_hand_motion(right_shape=.15), 2), MATCH_DISTANCE)

    def test_runtime_with_stationary_lead_in_fires_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CustomGestureStore(Path(tmp)/'empty.npz')
            store.data = empty_templates()
            store.data.update(sequences=np.array([circle()]),
                              sequence_names=np.array(['circle']), motions=np.array(['DYNAMIC']),
                              hand_counts=np.array([1]), durations=np.array([1.]))
            events = []
            for t in np.arange(0, 2, .05):
                progress = np.clip((t-.4), 0, 1) ** 1.65
                angle = progress * 2*np.pi
                h = hand(.4 + .09*np.cos(angle))
                h['landmarks'][:, 1] += .09*np.sin(angle)
                _, event, _, _ = store.update([h], float(t))
                if event:
                    events.append((t, event))
            self.assertEqual([e for _, e in events], ['circle'])
            self.assertGreaterEqual(events[0][0], 1.05)
            self.assertLessEqual(events[0][0], 1.6)

    def test_variable_speed_matches_without_changing_threshold(self):
        a, b = circle(), circle(power=1.65)
        self.assertLess(motion_matching_distance(a, b, 1), MATCH_DISTANCE)

    def test_reverse_direction_is_not_equivalent(self):
        self.assertGreaterEqual(motion_matching_distance(circle(), circle(reverse=True), 1), MATCH_DISTANCE)

    def test_incomplete_curve_is_not_a_complete_circle(self):
        self.assertGreaterEqual(motion_matching_distance(circle(), circle(partial=.65), 1), MATCH_DISTANCE)

    def test_different_finger_shape_remains_distinct(self):
        self.assertGreaterEqual(motion_matching_distance(circle(), circle(shape=.15), 1), MATCH_DISTANCE)

    def test_alignment_preserves_endpoints_and_bounded_path(self):
        a, b = circle(), circle(power=1.65)
        aligned = _align_curve(a, b)
        self.assertIsNotNone(aligned)
        aa, bb = aligned
        np.testing.assert_array_equal(aa[[0,-1]], a[[0,-1]])
        np.testing.assert_array_equal(bb[[0,-1]], b[[0,-1]])
        self.assertLessEqual(len(aa), 36)


if __name__ == '__main__':
    unittest.main()
