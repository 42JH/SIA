"""화면 경계 판정: 순간 튐, 연속 이탈, 반복 이탈 및 회차 분리."""
import unittest

from gesture_be import GestureRegistration


def hands(clipped=False, two=False):
    good = {'landmarks': [[0.5, 0.5] for _ in range(21)]}
    bad = {'landmarks': [[0.5, 0.5] for _ in range(21)]}
    bad['landmarks'][8][0] = 1.04 if clipped else 0.5
    return [good, bad] if two else [bad]


class FrameBoundsTests(unittest.TestCase):
    def registration(self, bad, n=61, step=1/30, two=False):
        reg = GestureRegistration(None, None, None)
        reg.temp_id = 'bounds'
        reg.take_frames = {1: [(i * step, hands(i in bad, two)) for i in range(n)]}
        return reg

    def test_one_bad_frame_allowed_even_in_short_take(self):
        self.registration({1}, n=4)._validate_frame_bounds()
        self.registration({30})._validate_frame_bounds()

    def test_brief_continuous_exit_is_allowed(self):
        self.registration(set(range(10, 17)))._validate_frame_bounds()

    def test_sustained_continuous_exit_is_rejected(self):
        reg = self.registration(set(range(10, 26)))
        with self.assertRaisesRegex(ValueError, '1회차.*손목과 손끝이 화면 안'):
            reg._validate_frame_bounds()

    def test_twenty_percent_intermittent_exit_is_allowed(self):
        self.registration(set(range(0, 60, 5)), n=60)._validate_frame_bounds()

    def test_frequent_intermittent_exit_is_rejected_by_ratio(self):
        with self.assertRaises(ValueError):
            self.registration(set(range(0, 60, 2)), n=60)._validate_frame_bounds()

    def test_rare_disjoint_spikes_allowed(self):
        self.registration({5, 20, 40})._validate_frame_bounds()

    def test_second_hand_is_checked(self):
        with self.assertRaises(ValueError):
            self.registration(set(range(20)), two=True)._validate_frame_bounds()

    def test_take_boundaries_do_not_join_runs(self):
        reg = self.registration({58, 59, 60})
        reg.take_frames[2] = [(3 + i/30, hands(i < 3)) for i in range(61)]
        reg._validate_frame_bounds()

    def test_missing_hand_breaks_continuity(self):
        reg = self.registration({10, 12})
        reg.take_frames[1][11] = (11/30, [])
        reg._validate_frame_bounds()

    def test_observation_gap_does_not_count_as_exit_duration(self):
        reg = self.registration({0, 1})
        reg.take_frames[1] = [(t + (0.4 if i else 0), h) for i, (t, h) in enumerate(reg.take_frames[1])]
        reg._validate_frame_bounds()


if __name__ == '__main__':
    unittest.main()
