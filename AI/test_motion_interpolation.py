"""Vectorized interpolation preserves the previous np.interp coordinate values."""
import unittest
import numpy as np
from custom_motion import _interpolate_frames


class InterpolationTests(unittest.TestCase):
    def test_irregular_times_and_clamped_boundaries(self):
        rng = np.random.default_rng(20260920)
        for count in (1, 2):
            times = np.cumsum(rng.uniform(.02,.08, size=35))
            points = rng.normal(size=(35,count,21,2)).astype(np.float32)
            grid = np.r_[times[0]-.1, np.linspace(times[0],times[-1],24),times[-1]+.1]
            flat = points.reshape(35,-1)
            expected = np.stack([np.interp(grid,times,col) for col in flat.T],axis=-1).reshape((len(grid),count,21,2))
            np.testing.assert_allclose(_interpolate_frames(times,points,grid),expected,rtol=0,atol=1e-14)


if __name__ == '__main__':
    unittest.main()
