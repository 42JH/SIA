import unittest

from gesture_be import GestureRegistration


def _hand(world=True, x=0.2):
    points = [(x + i * 0.001, 0.4 + i * 0.001) for i in range(21)]
    item = {"landmarks": points, "handedness": "Left" if x < 0.5 else "Right"}
    if world:
        item["world_landmarks"] = [(i * 0.001, i * 0.001, i * 0.001)
                                    for i in range(21)]
    else:
        item["world_landmarks"] = None
    return item


class TwoHandWorldQualityTests(unittest.TestCase):
    def _registration(self, frames):
        reg = GestureRegistration.__new__(GestureRegistration)
        reg.take_frames = {1: frames}
        return reg

    def test_partial_world_stream_is_measured(self):
        frames = [
            (0.0, [_hand(True, 0.2), _hand(True, 0.7)]),
            (0.1, [_hand(False, 0.2), _hand(False, 0.7)]),
        ]
        reg = self._registration(frames)
        self.assertAlmostEqual(reg._two_hand_world_coverage(1), 0.5)
        self.assertLess(reg._two_hand_world_coverage(1), reg.TWO_HAND_WORLD_MIN_RATIO)

    def test_completely_unavailable_world_stream_is_compatibility_fallback(self):
        frames = [
            (0.0, [_hand(False, 0.2), _hand(False, 0.7)]),
            (0.1, [_hand(False, 0.2), _hand(False, 0.7)]),
        ]
        reg = self._registration(frames)
        self.assertIsNone(reg._two_hand_world_coverage(1))


if __name__ == "__main__":
    unittest.main()
