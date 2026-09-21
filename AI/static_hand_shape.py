"""View/hand invariant distances between labelled 3D hand joints.

Joint identities retain finger bends, spread and thumb placement. Distances
discard camera rotation/reflection; vertical palm/thumb direction is retained
separately so an upward and downward pointing gesture are not merged.
No 3D information is fabricated for legacy 2D templates.
"""
import numpy as np

PAIRS = np.triu_indices(21, 1)
PAIR_COUNT = len(PAIRS[0])
FEATURE_SIZE = PAIR_COUNT + 2
STATIC_KEYS = ('static_shapes', 'static_shape_valid')
TIP_PAIRS = np.isin(PAIRS[0], [4, 8, 12, 16, 20]) & np.isin(PAIRS[1], [4, 8, 12, 16, 20])


def hand_shape(world):
    try:
        points = np.asarray(world, dtype=float)
    except (ValueError, TypeError):
        return None
    if points.shape != (21, 3) or not np.isfinite(points).all():
        return None
    scale = np.linalg.norm(points[9] - points[0])
    if scale < 1e-6:
        return None
    # Degenerate tracked fingers cannot be accepted as useful shape evidence.
    for start in (1, 5, 9, 13, 17):
        if np.min(np.linalg.norm(np.diff(points[start:start+4], axis=0), axis=1)) < scale*.02:
            return None
    thumb = points[4]-points[2]
    if np.linalg.norm(thumb) < scale*.02:
        return None
    distances = np.linalg.norm(points[PAIRS[0]]-points[PAIRS[1]], axis=1)/scale
    return np.r_[distances, (points[9,1]-points[0,1])/scale,
                 thumb[1]/np.linalg.norm(thumb)].astype(np.float32)


def shape_distances(templates, feature):
    # On the existing sqrt(21)-scaled landmark error scale. Keep the existing
    # runtime/registration thresholds; validate both against recorded negatives.
    diff = np.abs(templates-feature)
    # Do not dilute a meaningful finger-spread difference among 210 pairs.
    shape = diff[..., :PAIR_COUNT]
    return np.maximum(np.maximum(np.sqrt(21 * np.mean(shape**2, axis=-1)),
                                 2 * np.max(shape[..., TIP_PAIRS], axis=-1)),
                      2 * np.max(diff[..., PAIR_COUNT:], axis=-1))


def read_shapes(data, n):
    if not any(key in data for key in STATIC_KEYS):
        return np.zeros((n, FEATURE_SIZE), np.float32), np.zeros(n, bool)
    if not all(key in data for key in STATIC_KEYS):
        raise ValueError('Incomplete static 3D shape metadata')
    shapes = np.asarray(data['static_shapes'], dtype=np.float32)
    valid = np.asarray(data['static_shape_valid'], dtype=bool)
    if shapes.shape != (n, FEATURE_SIZE) or valid.shape != (n,) or not np.isfinite(shapes).all():
        raise ValueError('Invalid static 3D shape metadata')
    return shapes, valid
