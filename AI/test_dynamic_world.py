import unittest
import numpy as np
from custom_motion import FRAMES, MATCH_DISTANCE, motion_comparison


def pair():
    xy = np.zeros((FRAMES, 1, 21, 2), np.float32)
    world = np.zeros((FRAMES, 1, 21, 3), np.float32)
    for i in range(FRAMES):
        xy[i, 0, :, 0] = i * .01
        world[i, 0, :, 0] = i * .01
    return xy, world


class DynamicWorldTests(unittest.TestCase):
    def test_3d_is_used_when_both_templates_have_world_data(self):
        xy, world = pair()
        result = motion_comparison(xy, xy, 1, world_a=world, world_b=world)
        self.assertEqual(result['score_source'], '2D+WORLD_3D')
        self.assertEqual(result['score'], 0.0)

    def test_depth_shape_difference_is_visible_to_3d_path(self):
        xy, world = pair()
        changed = world.copy()
        changed[:, 0, 8, 2] = np.linspace(0, .8, FRAMES)
        plain_2d = motion_comparison(xy, xy, 1)['score']
        with_3d = motion_comparison(xy, xy, 1, world_a=world, world_b=changed)['score']
        self.assertEqual(plain_2d, 0.0)
        self.assertGreater(with_3d, plain_2d)
        self.assertTrue(with_3d < MATCH_DISTANCE)

    def test_missing_world_falls_back_to_existing_2d(self):
        xy, _ = pair()
        result = motion_comparison(xy, xy, 1)
        self.assertNotIn('world_score', result)
        self.assertEqual(result['score_source'] if 'score_source' in result else None, None)


if __name__ == '__main__':
    unittest.main()
