"""Versioned custom gesture templates: legacy poses and timed one/two-hand takes.

Coordinates retain relative hand placement and each hand's own shape. Only the
initial common translation and palm scale are removed; per-frame normalization
would erase the motion we want to recognize. For two hands, the average
tilt of the pair is also removed (see ROTATION_REF_MIN below) — that overall
lean is closer to camera-angle noise than to signal, while how the two hands
are angled *relative to each other* is kept, since that is what actually
distinguishes two-hand gestures from one another.
"""
import io
from collections import deque

import numpy as np

from hands import CustomGestures, LANDMARK_WEIGHTS, normalize_landmarks
from static_hand_shape import read_shapes, FEATURE_SIZE

FRAMES = 24
MATCH_DISTANCE = 0.22  # RMS landmark error, in initial palm lengths
PREFIX_DISTANCE = 0.16
PREFIX_MIN_MOTION = 0.08
DIRECTION_MIN_MOTION = 0.10
DIRECTION_TOLERANCE_DEG = 30.0
DIRECTION_NAMES_8 = (
    "RIGHT", "DOWN_RIGHT", "DOWN", "DOWN_LEFT",
    "LEFT", "UP_LEFT", "UP", "UP_RIGHT",
)
# 정적/동적 경계를 넘는 중복 검사(cross_boundary_matches, cross_legacy_matches)의
# 대상 폭. PREFIX_MIN_MOTION은 "동적으로 인정되려면 최소 이만큼은 움직여야 한다"는
# 등록 게이트라, 통과한 동적 시퀀스는 전부 이 값 이상 움직인다. 그중에서도 이
# 값의 2배 미만으로만 움직인, 즉 "동적이라 등록됐지만 거의 안 움직이는" 시퀀스만
# 정적 자세와 비교한다 — 원 그리기처럼 실제로 크게 움직이는 동작은, 궤적 중
# 어느 한 순간의 손모양이 우연히 같아도 비교 대상에서 뺀다.
CROSS_BOUNDARY_MOTION_MAX = PREFIX_MIN_MOTION * 2
# 2손 추적 중 ordered_landmarks가 한 프레임만 실패해도(핸디드니스 오판 등,
# 박수처럼 손이 가까워지는 동작에서 흔함) 즉시 추적 후보를 놓치지 않도록 주는
# 짧은 유예. latched(동작 완성 뒤 재무장 대기)의 0.3초와는 다른, 훨씬 짧은
# "이 프레임만 노이즈였을 뿐" 판단용 값이다.
TRACKING_GRACE_S = 0.15
POSE_JOINTS = (11, 12, 13, 14, 15, 16)  # shoulders, elbows, wrists
POSE_MIN_VISIBILITY = 0.35
POSE_MATCH_DISTANCE = 0.28
# 두 손 평균 방향 벡터(손목 중점→중지MCP 중점)의 최소 길이 — 이 값 미만이면
# "두 손이 거의 정반대를 향한다"는 뜻이라 회전 기준 자체가 정의되지 않는다.
# 길이 = 2*cos(두 손 사이 각도/2)이므로, 0.35는 두 손이 약 160도 이상
# 벌어졌을 때만 걸린다 — 보통의 2손 제스처(벌리기·교차 등)는 걸리지 않는
# 보수적인 값이다. 걸리면 보정을 건너뛰고 기존 동작(회전 미보정)으로 되돌아간다.
ROTATION_REF_MIN = 0.35
EXTRA_KEYS = ("sequences", "sequence_names", "motions", "hand_counts", "durations")
WORLD_KEYS = ("world_sequences", "world_valid")
# Put the view-invariant 3D error on the existing collision-score scale.  In
# captured three-take data the same two-hand pose stays below 0.10 raw error;
# opposing versus parallel palms are around 0.43, which must remain outside
# the registration collision threshold (0.45).
WORLD_DISTANCE_SCALE = 1.5


def empty_templates():
    return dict(X=np.empty((0, 42), np.float32), names=np.array([], dtype="U1"),
                static_shapes=np.empty((0, FEATURE_SIZE), np.float32),
                static_shape_valid=np.array([], dtype=bool),
                sequences=np.empty((0, FRAMES, 2, 21, 2), np.float32),
                sequence_names=np.array([], dtype="U1"), motions=np.array([], dtype="U7"),
                hand_counts=np.array([], dtype=np.int32), durations=np.array([], dtype=np.float32),
                world_sequences=np.empty((0, FRAMES, 2, 21, 3), np.float32),
                world_valid=np.array([], dtype=bool),
                pose_sequences=np.empty((0, FRAMES, len(POSE_JOINTS), 2), np.float32),
                pose_valid=np.array([], dtype=bool))


def normalize_arm_pose(landmarks):
    """Normalize shoulder/elbow/wrist pose for hand-occlusion fallback matching."""
    if landmarks is None or len(landmarks) <= max(POSE_JOINTS):
        return None
    selected = np.asarray([[landmarks[i][0], landmarks[i][1]] for i in POSE_JOINTS],
                          dtype=np.float32)
    visibility = np.asarray([landmarks[i][2] if len(landmarks[i]) > 2 else 0.0
                             for i in POSE_JOINTS], dtype=np.float32)
    if not np.isfinite(selected).all() or not np.isfinite(visibility).all():
        return None
    if np.any(visibility < POSE_MIN_VISIBILITY):
        return None
    shoulder_center = (selected[0] + selected[1]) * 0.5
    shoulder_width = float(np.linalg.norm(selected[0] - selected[1]))
    if shoulder_width < 0.05:
        return None
    return (selected - shoulder_center) / shoulder_width


def encode_pose_sequence(poses):
    """Store a robust static arm pose in the same time-shaped template format."""
    valid = [np.asarray(p, dtype=np.float32) for p in poses if p is not None]
    if not valid:
        return None
    pose = np.median(np.stack(valid), axis=0).astype(np.float32)
    return np.repeat(pose[None, ...], FRAMES, axis=0)


def pose_matching_distance(a, b):
    if a.shape != b.shape:
        return float("inf")
    return float(np.sqrt(np.mean(np.square(a - b))))


def _ordered_hands(hands):
    """Return the same stable hand order used by both 2D and world landmarks."""
    if len(hands) != 2:
        return list(hands)
    if {h.get("handedness") for h in hands} == {"Left", "Right"}:
        return sorted(hands, key=lambda h: h["handedness"])
    return sorted(hands, key=lambda h: h["landmarks"][0][0])


def hand_identity(hands):
    """추적 연속성 판단용 키. ordered_landmarks가 좌우 라벨 중복도 x좌표로
    복구하므로(같은 함수), 여기서도 그 경우를 진짜 좌우 정상 케이스와 같은
    값으로 취급해야 한다 — 안 그러면 정상적으로 복구된 프레임인데도 "손이
    바뀌었다"고 오인해 그때까지 쌓아 온 추적 이력을 지워버린다."""
    sides = tuple(h.get("handedness", "Unknown") for h in hands)
    if len(sides) == 2 and set(sides) != {"Left", "Right"}:
        return ("Left", "Right")
    return tuple(sorted(sides))


def ordered_landmarks(hands):
    if len(hands) not in (1, 2):
        return None
    if len(hands) == 2:
        # Never use detector output order (it can change between frames).
        if {h.get("handedness") for h in hands} == {"Left", "Right"}:
            hands = sorted(hands, key=lambda h: h["handedness"])
        else:
            # 기도처럼 두 손을 맞대는(좌우 대칭) 동작은 MediaPipe가 두 손 모두
            # 같은 손으로 잘못 분류하는 경우가 있다 — 순간적인 노이즈가 아니라
            # 그 동작 내내 지속될 수 있어(실측: 촬영 27프레임 중 10프레임이
            # 회차 전체에서 'Left','Left') TRACKING_GRACE_S로 덮을 수 없다.
            # 이 경우 프레임을 버리는 대신, 손목(랜드마크 0) x좌표로 순서를
            # 고정한다 — 어느 쪽이 실제 왼손인지는 중요하지 않고, 매 프레임
            # 같은 기준으로 정렬돼 순서가 안 바뀌기만 하면 된다.
            hands = sorted(hands, key=lambda h: h["landmarks"][0][0])
    points = np.asarray([h["landmarks"] for h in hands], dtype=np.float32)
    if points.shape != (len(hands), 21, 2) or not np.isfinite(points).all():
        return None
    if np.any(np.linalg.norm(points[:, 9] - points[:, 0], axis=-1) < 0.055):
        return None
    return points


def ordered_world_landmarks(hands):
    """World landmarks in exactly the same hand order as ordered_landmarks."""
    if len(hands) != 2:
        return None
    hands = _ordered_hands(hands)
    points = np.asarray([h.get("world_landmarks") for h in hands], dtype=np.float32)
    if points.shape != (2, 21, 3) or not np.isfinite(points).all():
        return None
    if np.any(np.linalg.norm(points[:, 9] - points[:, 0], axis=-1) < 1e-5):
        return None
    return points


def trim_motion_frames(frames, threshold=0.04):
    """손바닥 길이 기준 누적 변화를 보고 앞뒤 정지 구간만 제거한다.

    중간 멈춤과 방향 전환은 보존한다. 끝점 주변의 작은 떨림은 threshold
    이내로 허용하고, 움직임 경계 바로 바깥의 표본 하나는 남긴다.
    """
    if len(frames) < 3:
        return frames
    points = np.asarray([p for _, p in frames], dtype=np.float32)
    scale = max(float(np.linalg.norm(points[0, :, 9] - points[0, :, 0], axis=-1).mean()), 1e-6)
    def errors(reference):
        sq = np.sum(((points - reference) / scale) ** 2, axis=-1)
        return np.sqrt(np.mean(np.average(sq, axis=-1, weights=LANDMARK_WEIGHTS), axis=-1))
    starts = np.flatnonzero(errors(points[0]) > threshold)
    ends = np.flatnonzero(errors(points[-1]) > threshold)
    if not len(starts) or not len(ends):
        return frames
    first, last = max(0, int(starts[0]) - 1), min(len(frames) - 1, int(ends[-1]) + 1)
    return frames[first:last + 1] if last > first else frames


def _interpolate_frames(times, points, grid):
    """One shared interpolation index for every coordinate (np.interp semantics)."""
    times = np.asarray(times)
    upper = np.clip(np.searchsorted(times, grid, side='right'), 1, len(times)-1)
    lower = upper - 1
    weight = np.clip((grid-times[lower])/(times[upper]-times[lower]), 0, 1)
    weight = weight.reshape((len(grid),) + (1,)*(points.ndim-1))
    # Convert before subtracting, as np.interp also interpolates in float64.
    lo = points[lower].astype(np.float64)
    hi = points[upper].astype(np.float64)
    return lo + weight*(hi-lo)


def encode_sequence(times, points):
    times, points = np.asarray(times), np.asarray(points, dtype=np.float32)
    if len(times) < 2 or np.any(np.diff(times) <= 0):
        raise ValueError("촬영 시각이 올바르지 않습니다")
    origin = points[0, :, 0].mean(axis=0)
    scale = np.linalg.norm(points[0, :, 9] - points[0, :, 0], axis=-1).mean()
    normalized = (points - origin) / max(float(scale), 1e-6)
    if normalized.shape[1] == 2:
        # 두 손 각각의 손목→중지MCP 방향을 평균 내 "두 손이 대체로 향하는 방향"을
        # 구하고, 그 방향이 항상 위(0, -1)를 보도록 시퀀스 전체를 한 번 돌린다.
        # 프레임 0에서만 계산해 전체에 똑같이 적용한다(스케일·원점과 같은 방식) —
        # 매 프레임 다시 계산하면 자연스러운 진동에도 기준이 흔들릴 수 있다.
        ref = normalized[0, :, 9].mean(axis=0) - normalized[0, :, 0].mean(axis=0)
        ref_len = float(np.linalg.norm(ref))
        if ref_len > ROTATION_REF_MIN:
            angle = np.arctan2(float(ref[0]), -float(ref[1]))
            c, s = np.cos(-angle), np.sin(-angle)
            rot = np.array([[c, -s], [s, c]], dtype=np.float32)
            normalized = normalized @ rot.T
        # ref_len이 기준 미만이면(두 손이 거의 정반대를 향함) 회전 기준 자체가
        # 불안정하므로 보정을 건너뛴다 — 회전 미보정 상태(기존 동작)로 남는다.
    flat = normalized.reshape(len(times), -1)
    grid = np.linspace(times[0], times[-1], FRAMES)
    sampled = _interpolate_frames(times, flat, grid)
    result = np.zeros((FRAMES, 2, 21, 2), np.float32)
    result[:, :points.shape[1]] = sampled.reshape(FRAMES, points.shape[1], 21, 2)
    return result


def encode_world_sequence(times, points):
    """Encode one/two-hand 3D shape without using invalid inter-hand origins.

    MediaPipe world coordinates have a separate origin for each hand.  Each
    wrist is therefore centred independently; one shared scale keeps the two
    hand shapes comparable while their relative palm orientation is retained.
    """
    times, points = np.asarray(times), np.asarray(points, dtype=np.float32)
    if points.ndim != 4 or points.shape[1] not in (1, 2) or points.shape[2:] != (21, 3) or len(times) < 2:
        raise ValueError("invalid world landmark sequence")
    centred = points - points[:, :, :1]
    scale = np.linalg.norm(centred[0, :, 9], axis=-1).mean()
    centred /= max(float(scale), 1e-6)
    flat = centred.reshape(len(times), -1)
    grid = np.linspace(times[0], times[-1], FRAMES)
    sampled = np.stack([np.interp(grid, times, col) for col in flat.T], axis=-1)
    return sampled.reshape(FRAMES, points.shape[1], 21, 3).astype(np.float32)


def world_matching_distance(a, b):
    """View-invariant two-hand 3D pose distance using one shared rotation.

    A single Kabsch rotation is fitted to both hands together.  It removes a
    changed camera view but cannot rotate each palm independently, so prayer
    (opposing palms) remains distinct from a roof (roughly parallel palms).
    """
    values = []
    weights = np.tile(np.asarray(LANDMARK_WEIGHTS, dtype=np.float32), a.shape[1])
    weights /= weights.sum()
    for current, reference in zip(a, b):
        x = current.reshape(-1, 3)
        y = reference.reshape(-1, 3)
        covariance = (x * weights[:, None]).T @ y
        u, _, vt = np.linalg.svd(covariance)
        rotation = u @ vt
        if np.linalg.det(rotation) < 0:
            u[:, -1] *= -1
            rotation = u @ vt
        error = (x @ rotation) - y
        values.append(np.sum(weights * np.sum(error * error, axis=-1)))
    return float(np.sqrt(np.mean(values)))


def distance(a, b, count):
    """RMS 랜드마크 오차. 손끝(hands.LANDMARK_WEIGHTS)에 가중치를 둬 "구간 전체는
    비슷한데 손끝 모양만 다른" 오인식을 줄인다. 가중치 평균이 1일 때는 기존
    단순평균과 정확히 같은 값이 나와 MATCH_DISTANCE 등 기존 임계값을 그대로 쓴다.
    """
    sq = np.sum((a[:, :count] - b[:, :count]) ** 2, axis=-1)  # (FRAMES, count, 21)
    weighted = np.average(sq, axis=-1, weights=LANDMARK_WEIGHTS)  # (FRAMES, count)
    return float(np.sqrt(np.mean(weighted)))


def matching_distance(a, b, count):
    """한 손은 손목 궤적을 보존하고 손목 기준 손모양만 좌우 반전해 비교.

    프레임마다 유리한 손을 골라 붙이지 않고 시퀀스 전체에 같은 반전을 쓴다.
    양손은 좌우 역할/상대 위치를 보존하는 기존 비교를 그대로 사용한다.
    저장 좌표를 바꾸지 않으므로 기존 NPZ도 재등록 없이 비교할 수 있다.
    """
    direct = distance(a, b, count)
    if count != 1:
        return direct
    mirrored = np.array(b, copy=True)
    mirrored[:, 0, :, 0] = 2 * b[:, 0, 0:1, 0] - b[:, 0, :, 0]
    return min(direct, distance(a, mirrored, count))


def motion_features(sequence, count):
    """이동, 회전, 손가락 형태를 분리한다. 2D에서 관측 가능한 특징만 사용."""
    points = sequence[:, :count]
    wrists = points[:, :, 0]
    local = points - wrists[:, :, None]
    axis = local[:, :, 9]
    scale = np.maximum(np.linalg.norm(axis, axis=-1), 1e-6)
    up = axis / scale[..., None]
    right = np.stack([-up[..., 1], up[..., 0]], axis=-1)
    shape = np.stack([np.sum(local * right[:, :, None], axis=-1),
                      np.sum(local * up[:, :, None], axis=-1)], axis=-1) / scale[:, :, None, None]
    angles = np.arctan2(axis[..., 1], axis[..., 0])
    rotation = angles - angles[:1]
    separation = (np.linalg.norm(wrists[:, 1] - wrists[:, 0], axis=-1)
                  if count == 2 else np.zeros(len(points)))
    return dict(shape=shape, rotation=rotation, wrists=wrists,
                separation=separation - separation[0])


def motion_direction_8(sequence, count, min_motion=DIRECTION_MIN_MOTION):
    """Classify end-to-end wrist movement into one of eight screen sectors."""
    points = np.asarray(sequence, dtype=np.float32)
    if points.ndim != 4 or count not in (1, 2):
        return None
    start = points[0, :count, 0].mean(axis=0)
    end = points[-1, :count, 0].mean(axis=0)
    delta = end - start
    if float(np.linalg.norm(delta)) < min_motion:
        return None
    angle = float(np.arctan2(delta[1], delta[0]))
    sector = int(np.floor((angle + np.pi / 8) / (np.pi / 4))) % 8
    return DIRECTION_NAMES_8[sector]


def motion_direction_angle(sequence, count, min_motion=DIRECTION_MIN_MOTION):
    """Return the continuous end-to-end wrist angle, or None if too small."""
    points = np.asarray(sequence, dtype=np.float32)
    if points.ndim != 4 or count not in (1, 2):
        return None
    start = points[0, :count, 0].mean(axis=0)
    end = points[-1, :count, 0].mean(axis=0)
    delta = end - start
    if float(np.linalg.norm(delta)) < min_motion:
        return None
    return float(np.arctan2(delta[1], delta[0]))


def motion_direction_difference(a, b, count):
    """Smallest absolute movement-angle difference in degrees."""
    angle_a = motion_direction_angle(a, count)
    angle_b = motion_direction_angle(b, count)
    if angle_a is None or angle_b is None:
        return None
    delta = np.arctan2(np.sin(angle_a - angle_b), np.cos(angle_a - angle_b))
    return abs(float(np.degrees(delta)))


def motion_directions_compatible(a, b, count,
                                 tolerance_deg=DIRECTION_TOLERANCE_DEG):
    """Compare continuous angles so an 8-sector boundary is not a hard wall."""
    difference = motion_direction_difference(a, b, count)
    return difference is None or difference <= tolerance_deg


def swipe_direction_8(sequence, count, min_motion=DIRECTION_MIN_MOTION,
                      min_efficiency=0.70):
    """Return an 8-way direction only for a reasonably straight hand swipe.

    This applies the same displacement/path rule to vertical, horizontal and
    diagonal movement.  Curved or backtracking custom motions continue through
    normal template matching instead of being reduced to their end direction.
    """
    points = np.asarray(sequence, dtype=np.float32)
    if points.ndim != 4 or count not in (1, 2):
        return None
    wrists = points[:, :count, 0].mean(axis=1)
    delta = wrists[-1] - wrists[0]
    displacement = float(np.linalg.norm(delta))
    if displacement < min_motion:
        return None
    path_length = float(np.linalg.norm(np.diff(wrists, axis=0), axis=1).sum())
    if path_length <= 1e-6 or displacement / path_length < min_efficiency:
        return None
    return motion_direction_8(points, count, min_motion=min_motion)


def swipe_trajectory_distance(a, b, count):
    """Compare swipe paths independently of speed and travel distance."""
    direction_a = swipe_direction_8(a, count)
    direction_b = swipe_direction_8(b, count)
    if (direction_a is None or direction_b is None
            or not motion_directions_compatible(a, b, count)):
        return float('inf')
    wrists_a = np.asarray(a, dtype=np.float32)[:, :count, 0].mean(axis=1)
    wrists_b = np.asarray(b, dtype=np.float32)[:, :count, 0].mean(axis=1)
    wrists_a = wrists_a - wrists_a[:1]
    wrists_b = wrists_b - wrists_b[:1]
    travel_a = max(float(np.linalg.norm(wrists_a[-1])), 1e-6)
    travel_b = max(float(np.linalg.norm(wrists_b[-1])), 1e-6)
    delta = wrists_a / travel_a - wrists_b / travel_b
    return float(np.sqrt(np.mean(np.sum(delta ** 2, axis=-1))))


def _curved_motion(sequence, count):
    if count != 1 or len(sequence) < 6:
        return False
    path = sequence[:, 0, 0]
    length = float(np.linalg.norm(np.diff(path, axis=0), axis=-1).sum())
    return length >= DIRECTION_MIN_MOTION and np.linalg.norm(path[-1] - path[0]) < .70 * length


def _align_curve(a, b, count=1):
    """Bounded monotonic time alignment; preserve both endpoints and all frames.

    Never rotate, reverse, translate or scale the path. The five-frame band
    limits timing drift to about one fifth of a recording. A stretch penalty
    favours diagonal progress. Distant candidates are rejected before DP.
    """
    n = len(a)
    if n != FRAMES or len(b) != n:
        return None
    delta = a[:, None, :count] - b[None, :, :count]
    hand_cost = np.average(np.sum(delta ** 2, axis=-1), axis=-1,
                           weights=LANDMARK_WEIGHTS)
    cost = np.max(hand_cost, axis=-1)
    # A valid path visits every row/column, stays in the band and has at most
    # 1.5*n pairs. Bound the final mean landmark error, not the DP objective.
    band = np.abs(np.arange(n)[:, None] - np.arange(n)[None, :]) <= 5
    bound_cost = np.where(band, hand_cost.mean(axis=-1), np.inf)
    lower = max(float(bound_cost.min(axis=0).sum()), float(bound_cost.min(axis=1).sum())) / (n*1.5)
    if lower >= MATCH_DISTANCE ** 2:
        return None
    dp = np.full((n+1, n+1), np.inf)
    dp[0, 0] = 0
    back = np.zeros((n+1, n+1), dtype=np.int8)
    for i in range(1, n+1):
        for j in range(max(1, i-5), min(n, i+5)+1):
            choices = (dp[i-1, j-1], dp[i-1, j] + .0025, dp[i, j-1] + .0025)
            step = min(range(3), key=choices.__getitem__)
            dp[i, j] = choices[step] + cost[i-1, j-1]
            back[i, j] = step
    ia, ib = [], []
    i = j = n
    while i and j:
        ia.append(i-1)
        ib.append(j-1)
        step = back[i, j]
        if step != 2:
            i -= 1
        if step != 1:
            j -= 1
    if len(ia) > n * 1.5:
        return None
    return a[ia[::-1]], b[ib[::-1]]


def motion_comparison(a, b, count, _feature_cache=None, world_a=None, world_b=None):
    """동적 중복/실행/후보 검사 공통 점수. 한 특징 차이가 평균에 묻히지 않게 한다.

    각 손의 시간 RMS 중 큰 값을 사용한다. 거리와 형태는 손바닥 길이 단위,
    회전 변화는 라디안 단위이며 최댓값으로 판정한다. 확률이 아니다.
    한 손 반전은 모든 특징에 동일하게 적용하고 양손 역할은 바꾸지 않는다.
    """
    direction_a = motion_direction_8(a, count)
    direction_b = motion_direction_8(b, count)
    curved = _curved_motion(a, count) and _curved_motion(b, count)
    if (direction_a is not None and direction_b is not None
            and not curved
            and not motion_directions_compatible(a, b, count)):
        return dict(
            landmark=float('inf'), shape=float('inf'), rotation=float('inf'),
            wrist=float('inf'), separation=float('inf'), score=float('inf'),
            mirrored=False, direction=direction_a,
            reference_direction=direction_b, direction_match=False,
        )
    def features(sequence):
        if _feature_cache is None:
            return motion_features(sequence, count)
        key = (id(sequence), count)
        if key not in _feature_cache:
            # Retain the array too, preventing identity reuse within this frame.
            _feature_cache[key] = (sequence, motion_features(sequence, count))
        return _feature_cache[key][1]

    fa = features(a)
    def rms(v):
        return float(np.max(np.sqrt(np.mean(v ** 2, axis=0))))
    def compare(candidate, mirrored):
        fb = features(candidate)
        shape_delta = fa['shape'] - fb['shape']
        shape_sq = np.average(np.sum(shape_delta ** 2, axis=-1), axis=-1, weights=LANDMARK_WEIGHTS)
        shape = float(np.max(np.sqrt(np.mean(shape_sq, axis=0))))
        angle = fa['rotation'] - fb['rotation']
        angle = np.arctan2(np.sin(angle), np.cos(angle))
        wrist = np.linalg.norm((fa['wrists'] - fa['wrists'][:1]) - (fb['wrists'] - fb['wrists'][:1]), axis=-1)
        parts = dict(landmark=distance(a, candidate, count), shape=shape,
                     rotation=rms(angle), wrist=rms(wrist),
                     separation=rms(fa['separation'] - fb['separation']))
        return dict(**parts, score=max(parts.values()), mirrored=mirrored,
                    direction=direction_a, reference_direction=direction_b,
                    direction_match=True)
    result = compare(b, False)
    if count == 1:
        mirrored = np.array(b, copy=True)
        mirrored[:, 0, :, 0] = 2 * b[:, 0, 0:1, 0] - b[:, 0, :, 0]
        alternate = compare(mirrored, True)
        if alternate['score'] < result['score']:
            result = alternate
    swipe_trajectory = swipe_trajectory_distance(a, b, count)
    if np.isfinite(swipe_trajectory):
        # Travel distance and speed naturally vary between repeated swipes, so
        # use the normalized wrist path.  The path alone is insufficient:
        # otherwise an open-palm swipe and a fist swipe in the same direction
        # become duplicates.  Preserve the rotation-normalized finger-shape
        # distance as an independent requirement.
        swipe_score = max(swipe_trajectory, result['shape'])
        if swipe_score < result['score']:
            result.update(score=swipe_score, score_source="SWIPE_TRAJECTORY_SHAPE",
                          swipe_trajectory=swipe_trajectory,
                          swipe_direction=swipe_direction_8(a, count))
    # Both hands share one time path. Never independently warp, swap or
    # reflect them: their relative timing and separation carry meaning.
    two_hand_motion = (count == 2
                       and distance(a, np.repeat(a[:1], len(a), axis=0), 2) >= PREFIX_MIN_MOTION
                       and distance(b, np.repeat(b[:1], len(b), axis=0), 2) >= PREFIX_MIN_MOTION)
    if (curved or two_hand_motion) and result['score'] >= MATCH_DISTANCE:
        candidates = ((b, False), (mirrored, True)) if count == 1 else ((b, False),)
        for candidate, is_mirrored in candidates:
            aligned = _align_curve(a, candidate, count)
            if aligned is None:
                continue
            # Already selected handedness; prevent a second reflection.
            aa, bb = aligned
            fa, fb = motion_features(aa, count), motion_features(bb, count)
            shape_sq = np.average(np.sum((fa['shape'] - fb['shape']) ** 2, axis=-1),
                                  axis=-1, weights=LANDMARK_WEIGHTS)
            angle = fa['rotation'] - fb['rotation']
            angle = np.arctan2(np.sin(angle), np.cos(angle))
            wrist = np.linalg.norm((fa['wrists'] - fa['wrists'][:1]) -
                                   (fb['wrists'] - fb['wrists'][:1]), axis=-1)
            parts = dict(landmark=distance(aa, bb, count),
                         shape=float(np.max(np.sqrt(np.mean(shape_sq, axis=0)))),
                         rotation=rms(angle), wrist=rms(wrist),
                         separation=rms(fa['separation'] - fb['separation']))
            score = max(parts.values())
            if score < result['score']:
                result.update(**parts, score=score, mirrored=is_mirrored,
                              score_source='ALIGNED_CURVE' if count == 1 else 'ALIGNED_TWO_HAND',
                              aligned_pairs=len(aa))
    if (world_a is not None and world_b is not None
            and world_a.shape == world_b.shape and world_a.shape[1] == count):
        world_score = 1.5 * world_matching_distance(world_a, world_b)
        result['world_score'] = world_score
        result['score'] = max(result['score'], world_score)
        result['score_source'] = '2D+WORLD_3D'
    return result


def motion_matching_distance(a, b, count, _feature_cache=None):
    return motion_comparison(a, b, count, _feature_cache)['score']


def prefix_sequence(sequence, fraction):
    """Resample the start of a template, preserving its original coordinate frame."""
    grid = np.linspace(0, (FRAMES - 1) * fraction, FRAMES)
    return _interpolate_frames(np.arange(FRAMES), sequence, grid)


def static_execution_allowed(active, registering, claimed, custom_pose, name):
    # Explicitly bypass GestureStable's missing-grace output during a candidate.
    return active and not registering and (not claimed or custom_pose == name)


def read_templates(payload, name=None):
    result = empty_templates()
    with np.load(io.BytesIO(payload), allow_pickle=False) as data:
        if "schema_version" in data and int(data["schema_version"]) not in (2, 3, 4):
            raise ValueError("지원하지 않는 제스처 템플릿 버전입니다")
        for key in result:
            if key in data:
                result[key] = np.array(data[key])
        result["static_shapes"], result["static_shape_valid"] = read_shapes(data, len(result["X"]))
    x, seq = result["X"], result["sequences"]
    if x.ndim != 2 or x.shape[1:] != (42,) or not np.isfinite(x).all():
        raise ValueError("잘못된 정적 제스처 템플릿입니다")
    if result["names"].shape != (len(x),):
        raise ValueError("정적 라벨 수가 일치하지 않습니다")
    if seq.shape != (len(seq), FRAMES, 2, 21, 2) or not np.isfinite(seq).all():
        raise ValueError("잘못된 동작 제스처 템플릿입니다")
    for key in EXTRA_KEYS[1:]:
        if result[key].shape != (len(seq),):
            raise ValueError("동작 메타데이터 수가 일치하지 않습니다")
    if result["world_sequences"].shape != (len(seq), FRAMES, 2, 21, 3):
        result["world_sequences"] = np.zeros((len(seq), FRAMES, 2, 21, 3), np.float32)
        result["world_valid"] = np.zeros(len(seq), dtype=bool)
    if result["world_valid"].shape != (len(seq),):
        raise ValueError("invalid world landmark metadata")
    if result["pose_sequences"].shape != (len(seq), FRAMES, len(POSE_JOINTS), 2):
        result["pose_sequences"] = np.zeros(
            (len(seq), FRAMES, len(POSE_JOINTS), 2), np.float32)
        result["pose_valid"] = np.zeros(len(seq), dtype=bool)
    if result["pose_valid"].shape != (len(seq),):
        raise ValueError("invalid body pose metadata")
    if not np.isin(result["hand_counts"], [1, 2]).all() or not np.isin(result["motions"], ["STATIC", "DYNAMIC"]).all():
        raise ValueError("잘못된 손 수 또는 동작 종류입니다")
    if not np.isfinite(result["durations"]).all() or np.any(result["durations"] <= 0) or np.any(result["durations"] > 30):
        raise ValueError("촬영 길이는 0초 초과 30초 이하여야 합니다")
    if not len(x) and not len(seq):
        raise ValueError("빈 제스처 템플릿입니다")
    if name is not None:
        result["names"] = np.array([name] * len(x))
        result["sequence_names"] = np.array([name] * len(seq))
    return result


def template_bytes(data):
    out = io.BytesIO()
    np.savez_compressed(out, schema_version=np.array(4), **data)
    return out.getvalue()


class CustomGestureStore:
    """Read legacy NPZ and version 2 templates without mixing feature dimensions."""
    def __init__(self, path):
        from pathlib import Path
        self.legacy = CustomGestures(path)
        self.data = read_templates(Path(path).read_bytes()) if Path(path).exists() else empty_templates()
        self.history = deque(maxlen=1000)
        self.world_history = deque(maxlen=1000)
        self.latched = False
        self.latched_name = None
        self.missing_since = None
        self._last_claimed = False  # 가장 최근 정상 프레임의 claimed — 찰나의 추적 실패를 이어붙이는 데 쓴다
        self._curve_prefix = None

    @property
    def n(self):
        return self.legacy.n + len(self.data["sequences"])

    def class_names(self):
        return sorted(set(self.legacy.class_names()) | set(self.data["sequence_names"]))

    def nearest_class(self, feats, shapes=None):
        return self.legacy.nearest_class(feats, shapes=shapes)

    def classify_with_distance(self, landmarks, disabled=(), world_landmarks=None):
        return self.legacy.classify_with_distance(landmarks, disabled=disabled, world_landmarks=world_landmarks)

    def sequence_comparisons(self, sequence, motion, count, world_sequence=None):
        # 기존 템플릿도 비교할 때만 정지 구간을 잘라 신규 촬영과 기준을 맞춘다.
        # 원본 파일과 실행용 템플릿은 여기서 변경하지 않는다.
        def comparison(seq):
            if motion != "DYNAMIC":
                return seq
            frames = trim_motion_frames(list(zip(np.linspace(0, 1, len(seq)), seq[:, :count])))
            return encode_sequence([t for t, _ in frames], [p for _, p in frames])
        sequence = comparison(sequence)
        candidates = []
        for index, (s, name, m, h) in enumerate(zip(*(self.data[k] for k in EXTRA_KEYS[:4]))):
            if m != motion or h != count:
                continue
            reference = comparison(s)
            world_reference = (self.data["world_sequences"][index]
                               if index < len(self.data["world_valid"])
                               and bool(self.data["world_valid"][index]) else None)
            details = (motion_comparison(sequence, reference, count,
                                         world_a=world_sequence,
                                         world_b=world_reference)
                       if motion == 'DYNAMIC'
                       else dict(score=matching_distance(sequence, reference, count)))
            if (motion == "STATIC" and count == 2 and world_sequence is not None
                    and bool(self.data["world_valid"][index])):
                world_score = WORLD_DISTANCE_SCALE * world_matching_distance(
                    world_sequence, self.data["world_sequences"][index])
                details.update(score=world_score, world_score=world_score,
                               score_source="WORLD_3D")
            candidates.append(dict(template_index=index, name=str(name), **details))
        return sorted(candidates, key=lambda item: item['score'])

    def nearest_sequence(self, sequence, motion, count):
        candidates = self.sequence_comparisons(sequence, motion, count)
        return ((candidates[0]['score'], candidates[0]['name']) if candidates
                else (float('inf'), None))

    def cross_boundary_matches(self, sequence, motion, count):
        """같은 손 개수라도 동작 종류(motion)가 반대인 저장 템플릿과도 손모양
        중복을 본다. sequence_comparisons는 motion이 같아야만 비교하므로,
        같은 손모양을 정적으로 한 번, 동적으로 한 번 등록하면 서로 못 본다 —
        이 함수가 그 경계를 넘는 부분만 추가로 확인한다.

        동적은 동적끼리, 정적은 정적끼리만 비교한다는 원칙은 그대로 지킨다 —
        다만 동적으로 등록됐어도 실제로는 거의 움직이지 않은 시퀀스
        (CROSS_BOUNDARY_MOTION_MAX 미만)는 "정적을 동적으로 잘못 등록한 것"으로
        보고, 그 프레임들을 평균 내 자세 하나로 접은 뒤 그 자세만 비교한다.
        시퀀스의 개별 프레임과 비교하지 않으므로, "원 그리기"처럼 실제로 뚜렷이
        움직이는 동작은 궤적 중 한 순간이 우연히 같아도 걸리지 않는다.
        """
        other = 'DYNAMIC' if motion == 'STATIC' else 'STATIC'
        candidates = []
        for s, name, m, h in zip(*(self.data[k] for k in EXTRA_KEYS[:4])):
            if h != count or m != other:
                continue
            dynamic_seq = s if motion == 'STATIC' else sequence
            movement = distance(dynamic_seq, np.repeat(dynamic_seq[:1], dynamic_seq.shape[0], axis=0), count)
            if movement >= CROSS_BOUNDARY_MOTION_MAX:
                continue
            folded = np.repeat(dynamic_seq.mean(axis=0, keepdims=True), dynamic_seq.shape[0], axis=0)
            a, b = (sequence, folded) if motion == 'STATIC' else (folded, s)
            candidates.append((matching_distance(a, b, count), str(name)))
        return sorted(candidates)

    def cross_legacy_matches(self, sequence, count):
        """1손 동적 시퀀스가 1손 정적(legacy kNN) 저장소의 기존 자세와 얼마나
        가까운지 본다. 1손 정적은 self.data가 아니라 legacy에 저장되므로
        cross_boundary_matches가 보지 못하는 경계다.

        cross_boundary_matches와 같은 원칙 — 이 시퀀스 자체가 실제로 크게
        움직였다면(CROSS_BOUNDARY_MOTION_MAX 이상) 비교하지 않는다. 거의 안
        움직인 경우에도 매 프레임과 비교하지 않고, 전체를 평균 내 자세 하나로
        접어 그 자세 하나만 정적 저장소와 비교한다(정적 대 정적 비교 유지).
        """
        if count != 1 or self.legacy.n == 0:
            return None, float('inf')
        movement = distance(sequence, np.repeat(sequence[:1], sequence.shape[0], axis=0), count)
        if movement >= CROSS_BOUNDARY_MOTION_MAX:
            return None, float('inf')
        pose = sequence[:, 0].mean(axis=0)
        if np.linalg.norm(pose[9] - pose[0]) <= 1e-6:
            return None, float('inf')
        return self.legacy.nearest_class([normalize_landmarks(pose)])

    def reset_motion(self):
        self.history.clear()
        self.world_history.clear()
        self.latched = False
        self.latched_name = None
        self.missing_since = None
        self._last_claimed = False
        self._curve_prefix = None

    def _curve_prefix_claimed(self, now, count, disabled):
        """Track a moving curved prefix from its onset, with phase alignment.

        Acquire at PREFIX_DISTANCE; continue only the same progressing prefix
        inside the existing final-match distance. Straight motion never enters
        this path. Missing input, a stop or a changed onset releases the claim.
        """
        previous = self._curve_prefix
        self._curve_prefix = None
        if count != 1 or len(self.history) < 6:
            return False
        frames = trim_motion_frames([(t, p) for t, p, _ in self.history])
        if len(frames) < 6 or now - frames[-1][0] > TRACKING_GRACE_S:
            return False
        current = encode_sequence([t for t, _ in frames], [p for _, p in frames])
        wrists = current[:, 0, 0] - current[0, 0, 0]
        travel = float(np.linalg.norm(np.diff(wrists, axis=0), axis=-1).sum())
        # Same straightness boundary as swipe_direction_8. Require movement,
        # so noisy stationary hands cannot reserve a command.
        if (travel < DIRECTION_MIN_MOTION
                or float(np.linalg.norm(wrists[-1])) / travel >= .70
                or distance(current, np.repeat(current[:1], FRAMES, axis=0), 1) < PREFIX_MIN_MOTION):
            return False
        elapsed = frames[-1][0] - frames[0][0]
        best = None
        for index, (seq, name, motion, n, duration) in enumerate(
                zip(*(self.data[k] for k in EXTRA_KEYS))):
            if motion != 'DYNAMIC' or n != 1 or name in disabled:
                continue
            path = seq[:, 0, 0] - seq[0, 0, 0]
            length = float(np.linalg.norm(np.diff(path, axis=0), axis=-1).sum())
            if length < DIRECTION_MIN_MOTION or float(np.linalg.norm(path[-1])) / length >= .70:
                continue
            continuing = (previous is not None and previous['index'] == index
                          and previous['name'] == str(name)
                          and abs(previous['onset'] - frames[0][0]) < 1e-6
                          and now - previous['advanced_at'] <= TRACKING_GRACE_S)
            threshold = MATCH_DISTANCE if continuing else PREFIX_DISTANCE
            for fraction in np.linspace(.25, .975, 30):
                if not .5 <= elapsed / (float(duration) * fraction) <= 1.5:
                    continue
                if continuing and fraction < previous['fraction'] - .025:
                    continue
                expected = prefix_sequence(seq, float(fraction))
                expected_wrists = expected[:, 0, 0] - expected[0, 0, 0]
                # Cheap lower bound before comparing hand shape/rotation.
                wrist_error = float(np.sqrt(np.mean(np.sum((wrists - expected_wrists) ** 2, axis=-1))))
                if wrist_error >= threshold:
                    continue
                score = motion_matching_distance(current, expected, 1)
                if score >= threshold or (best is not None and score >= best[0]):
                    continue
                advancing = not continuing or fraction > previous['fraction'] + 1e-6
                state = dict(index=index, name=str(name), onset=frames[0][0],
                             fraction=float(fraction),
                             advanced_at=now if advancing else previous['advanced_at'])
                best = score, state
        if best is not None:
            self._curve_prefix = best[1]
            return True
        return False

    def update(self, hands, now, disabled=(), pose_landmarks=None):
        """Return (held two-hand pose, completed motion, suppress other commands, distance).

        Motion fires once, then requires hands to leave for 0.3 s before rearming.
        Missing/ambiguous hands and long camera gaps cannot bridge a trajectory.
        distance is the winning template's landmark distance whenever a static
        hold or a completed motion is returned, otherwise None — callers use it
        to derive a confidence score (e.g. exp(-distance)) for stats.
        """
        if self.latched_name in disabled:
            self.reset_motion()
        points = ordered_landmarks(hands)
        arm_pose = normalize_arm_pose(pose_landmarks)
        # 양손 후보를 추적하던 중 한 손만 검출되면 새 한손 동작으로 섞지 않는다.
        two_hand_gap = (len(hands) == 1 and self.history
                        and len(self.history[-1][1]) == 2
                        and any(n == 2 and name not in disabled for n, name in
                                zip(self.data['hand_counts'], self.data['sequence_names'])))
        if two_hand_gap:
            points = None
        if points is None:
            # Hands may be hidden by crossed arms or another hand. Use body
            # pose only for static templates that were registered with it.
            if arm_pose is not None:
                current_pose = encode_pose_sequence([arm_pose])
                best_pose = (POSE_MATCH_DISTANCE, None)
                for index, (name, motion) in enumerate(zip(
                        self.data["sequence_names"], self.data["motions"])):
                    if (motion != "STATIC" or name in disabled
                            or not bool(self.data["pose_valid"][index])):
                        continue
                    score = pose_matching_distance(
                        current_pose, self.data["pose_sequences"][index])
                    if score < best_pose[0]:
                        best_pose = score, str(name)
                if best_pose[1] is not None:
                    self.missing_since = None
                    self._last_claimed = True
                    return best_pose[1], None, True, best_pose[0]
            # ordered_landmarks는 핸디드니스가 한 프레임만 애매해도(두 손이 순간
            # 같은 쪽으로 잡히는 등, 손이 가까워지는 동작에서 흔함) None을 낸다.
            # 그 찰나에 바로 추적 후보를 놓치면(claimed=False) 호출측이 그 프레임의
            # 원본 raw 판정(1손 내장/커스텀)으로 새서 엉뚱한 게 발동할 수 있다 —
            # TRACKING_GRACE_S 동안은 이력을 유지하고, 직전 정상 프레임이 실제로
            # "추적 중(claimed)"이었을 때만 그 상태를 이어준다 — 손이 있었다는
            # 사실 자체(self.history)가 아니라 그때 진짜 후보를 물고 있었는지를
            # 봐야, 아무 매칭도 없는 상태에서 글리치만으로 claimed가 켜지지 않는다.
            # latched(완성 뒤 재무장 대기)의 0.3초 유예는 별개 개념이라 그대로 둔다.
            had_progress = self._last_claimed
            if self.missing_since is None:
                self.missing_since = self.history[-1][0] if self.history else now
            elapsed = now - self.missing_since
            if elapsed >= TRACKING_GRACE_S:
                self.history.clear()
                self.world_history.clear()
                self._curve_prefix = None
            if elapsed >= 0.3:
                self.latched = False
            claimed = self.latched or (elapsed < TRACKING_GRACE_S and had_progress)
            return None, None, claimed, None
        if self.missing_since is not None and now - self.missing_since >= TRACKING_GRACE_S:
            self.history.clear()
            self.world_history.clear()
            self._last_claimed = False
            self._curve_prefix = None
        self.missing_since = None
        if self.latched:
            self._last_claimed = True
            return None, None, True, None
        identity = hand_identity(hands)
        if self.history and (now - self.history[-1][0] > 0.25 or now <= self.history[-1][0]
                             or identity != self.history[-1][2]):
            self.history.clear()
            self.world_history.clear()
            self._curve_prefix = None
        if not self.history or now - self.history[-1][0] >= 0.05:
            self.history.append((now, points, identity))
            world_points = None
            if len(points) in (1, 2):
                candidates = [h.get('world_landmarks') for h in hands]
                wp = np.asarray(candidates, dtype=np.float32)
                if wp.shape == (len(points), 21, 3) and np.isfinite(wp).all():
                    world_points = wp
            self.world_history.append((now, world_points))
        count = len(points)
        current_world = None
        if count == 2:
            world_points = ordered_world_landmarks(hands)
            if world_points is not None:
                current_world = encode_world_sequence([0, 1], [world_points, world_points])
        best_static, best_dynamic = (MATCH_DISTANCE, None), (MATCH_DISTANCE, None)
        pending_motion = False
        sequence_cache = {}
        movement_cache = {}
        feature_cache = {}

        def sequence_for(window):
            # History is immutable during this update. Equal endpoints select
            # the same samples, so repeated template windows share encoding.
            key = (window[0][0], window[-1][0])
            if key not in sequence_cache:
                sequence_cache[key] = encode_sequence([v[0] for v in window], [v[1] for v in window])
            return sequence_cache[key]

        for index, (seq, name, motion, n, duration) in enumerate(
                zip(*(self.data[k] for k in EXTRA_KEYS))):
            if count != n or name in disabled:
                continue
            if motion == "STATIC":
                current = encode_sequence([0, 1], [points, points])
                if (count == 2 and current_world is not None
                        and bool(self.data["world_valid"][index])):
                    score = WORLD_DISTANCE_SCALE * world_matching_distance(
                        current_world, self.data["world_sequences"][index])
                else:
                    score = matching_distance(current, seq, count)
                if score < best_static[0]:
                    best_static = score, str(name)
                continue
            speeds = (0.7, 1.0, 1.3)
            # 실제 속도가 이 세 배수 사이(예: 0.85배)에 끼면, 가장 가까운 배수조차
            # 그 시점까지 쌓인 실제 시간보다 더 긴 구간을 요구해 통과 못 하거나,
            # 통과해도 그 구간이 동작의 앞부분을 잘라낸 "뒤쪽 일부"만 담게 된다.
            # 별 그리기처럼 구간마다 모양이 뚜렷이 다른 동작은 이 잘림만으로도
            # 기준(MATCH_DISTANCE)을 넘겨버린다(실측: 15% 빠르게 재현 시 0.295).
            # 실제로 쌓인 구간 길이를 배수로 환산해 하나 더 시도하면, 몇 배로
            # 봐야 할지 추측하지 않고 "지금까지 관측된 전체"를 그대로 비교하게
            # 되어 이 잘림이 사라진다 — 말도 안 되게 짧거나 긴 경우만 배제한다.
            if self.history:
                actual_span = self.history[-1][0] - self.history[0][0]
                actual_speed = actual_span / float(duration)
                if 0.5 <= actual_speed <= 1.5:
                    speeds = speeds + (actual_speed,)
            for speed in speeds:
                span = float(duration) * speed
                # Look for actual movement matching a template prefix before a
                # built-in hold can fire. A stationary matching pose alone must
                # not reserve execution. Rolling prefixes allow a neutral lead-in.
                if not pending_motion:
                    for length in sorted({0.2, 0.4, span * 0.35, span * 0.6, span * 0.85}):
                        if length >= span:
                            continue
                        prefix_window = [item for item in self.history if item[0] >= now - length - 0.04]
                        if len(prefix_window) < 3:
                            continue
                        elapsed = prefix_window[-1][0] - prefix_window[0][0]
                        if elapsed < length * 0.85:
                            continue
                        current_prefix = sequence_for(prefix_window)
                        key = (prefix_window[0][0], prefix_window[-1][0])
                        if key not in movement_cache:
                            movement_cache[key] = distance(current_prefix, np.repeat(current_prefix[:1], FRAMES, axis=0), count)
                        movement = movement_cache[key]
                        if movement < PREFIX_MIN_MOTION:
                            continue
                        expected = prefix_sequence(seq, min(1.0, elapsed / span))
                        if motion_matching_distance(current_prefix, expected, count, feature_cache) < PREFIX_DISTANCE:
                            pending_motion = True
                            break
                window = [item for item in self.history if item[0] >= now - span - 0.04]
                if len(window) < 6 or window[-1][0] - window[0][0] < span * 0.9:
                    continue
                current = sequence_for(window)
                world_window = [item for item in self.world_history
                                if item[0] >= now - span - 0.04 and item[1] is not None]
                current_world = None
                if (len(world_window) >= 6 and len(world_window) == len(window)
                        and all(item[1].shape[0] == count for item in world_window)):
                    current_world = encode_world_sequence(
                        [item[0] for item in world_window], [item[1] for item in world_window])
                if _curved_motion(seq, count):
                    # Registration removes stationary lead-in/out before
                    # normalizing its origin. Use that same active interval
                    # at execution, retaining the existing speed floor.
                    active = trim_motion_frames([(v[0], v[1]) for v in window])
                    if (len(active) >= 6
                            and active[-1][0] - active[0][0] >= float(duration) * .5):
                        current = sequence_for(active)
                reference_world = (self.data['world_sequences'][index]
                                   if index < len(self.data['world_valid'])
                                   and bool(self.data['world_valid'][index]) else None)
                details = motion_comparison(current, seq, count, feature_cache,
                                            world_a=current_world, world_b=reference_world)
                score = details['score']
                if score < best_dynamic[0]:
                    best_dynamic = score, str(name)
        if best_dynamic[1]:
            self.latched = True
            self.latched_name = best_dynamic[1]
            self.history.clear()
            self.world_history.clear()
            self._last_claimed = True
            return None, best_dynamic[1], True, best_dynamic[0]
        curve_pending = self._curve_prefix_claimed(now, count, disabled)
        if pending_motion or curve_pending:
            self._last_claimed = True
            return None, None, True, None
        self._last_claimed = bool(best_static[1])
        return best_static[1], None, self._last_claimed, (best_static[0] if best_static[1] else None)
