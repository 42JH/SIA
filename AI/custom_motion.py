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

from hands import CustomGestures, LANDMARK_WEIGHTS

FRAMES = 24
MATCH_DISTANCE = 0.22  # RMS landmark error, in initial palm lengths
PREFIX_DISTANCE = 0.16
PREFIX_MIN_MOTION = 0.08
# 두 손 평균 방향 벡터(손목 중점→중지MCP 중점)의 최소 길이 — 이 값 미만이면
# "두 손이 거의 정반대를 향한다"는 뜻이라 회전 기준 자체가 정의되지 않는다.
# 길이 = 2*cos(두 손 사이 각도/2)이므로, 0.35는 두 손이 약 160도 이상
# 벌어졌을 때만 걸린다 — 보통의 2손 제스처(벌리기·교차 등)는 걸리지 않는
# 보수적인 값이다. 걸리면 보정을 건너뛰고 기존 동작(회전 미보정)으로 되돌아간다.
ROTATION_REF_MIN = 0.35
EXTRA_KEYS = ("sequences", "sequence_names", "motions", "hand_counts", "durations")


def empty_templates():
    return dict(X=np.empty((0, 42), np.float32), names=np.array([], dtype="U1"),
                sequences=np.empty((0, FRAMES, 2, 21, 2), np.float32),
                sequence_names=np.array([], dtype="U1"), motions=np.array([], dtype="U7"),
                hand_counts=np.array([], dtype=np.int32), durations=np.array([], dtype=np.float32))


def ordered_landmarks(hands):
    if len(hands) not in (1, 2):
        return None
    if len(hands) == 2:
        # Never use detector output order (it can change between frames).
        if {h.get("handedness") for h in hands} != {"Left", "Right"}:
            return None
        hands = sorted(hands, key=lambda h: h["handedness"])
    points = np.asarray([h["landmarks"] for h in hands], dtype=np.float32)
    if points.shape != (len(hands), 21, 2) or not np.isfinite(points).all():
        return None
    if np.any(np.linalg.norm(points[:, 9] - points[:, 0], axis=-1) < 0.055):
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
    sampled = np.stack([np.interp(grid, times, col) for col in flat.T], axis=-1)
    result = np.zeros((FRAMES, 2, 21, 2), np.float32)
    result[:, :points.shape[1]] = sampled.reshape(FRAMES, points.shape[1], 21, 2)
    return result


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


def motion_comparison(a, b, count):
    """동적 중복/실행/후보 검사 공통 점수. 한 특징 차이가 평균에 묻히지 않게 한다.

    각 손의 시간 RMS 중 큰 값을 사용한다. 거리와 형태는 손바닥 길이 단위,
    회전 변화는 라디안 단위이며 최댓값으로 판정한다. 확률이 아니다.
    한 손 반전은 모든 특징에 동일하게 적용하고 양손 역할은 바꾸지 않는다.
    """
    fa = motion_features(a, count)
    def rms(v):
        return float(np.max(np.sqrt(np.mean(v ** 2, axis=0))))
    def compare(candidate, mirrored):
        fb = motion_features(candidate, count)
        shape_delta = fa['shape'] - fb['shape']
        shape_sq = np.average(np.sum(shape_delta ** 2, axis=-1), axis=-1, weights=LANDMARK_WEIGHTS)
        shape = float(np.max(np.sqrt(np.mean(shape_sq, axis=0))))
        angle = fa['rotation'] - fb['rotation']
        angle = np.arctan2(np.sin(angle), np.cos(angle))
        wrist = np.linalg.norm((fa['wrists'] - fa['wrists'][:1]) - (fb['wrists'] - fb['wrists'][:1]), axis=-1)
        parts = dict(landmark=distance(a, candidate, count), shape=shape,
                     rotation=rms(angle), wrist=rms(wrist),
                     separation=rms(fa['separation'] - fb['separation']))
        return dict(**parts, score=max(parts.values()), mirrored=mirrored)
    result = compare(b, False)
    if count == 1:
        mirrored = np.array(b, copy=True)
        mirrored[:, 0, :, 0] = 2 * b[:, 0, 0:1, 0] - b[:, 0, :, 0]
        alternate = compare(mirrored, True)
        if alternate['score'] < result['score']:
            result = alternate
    return result


def motion_matching_distance(a, b, count):
    return motion_comparison(a, b, count)['score']


def prefix_sequence(sequence, fraction):
    """Resample the start of a template, preserving its original coordinate frame."""
    grid = np.linspace(0, (FRAMES - 1) * fraction, FRAMES)
    flat = sequence.reshape(FRAMES, -1)
    return np.stack([np.interp(grid, np.arange(FRAMES), col) for col in flat.T], axis=-1).reshape(sequence.shape)


def static_execution_allowed(active, registering, claimed, custom_pose, name):
    # Explicitly bypass GestureStable's missing-grace output during a candidate.
    return active and not registering and (not claimed or custom_pose == name)


def read_templates(payload, name=None):
    result = empty_templates()
    with np.load(io.BytesIO(payload), allow_pickle=False) as data:
        if "schema_version" in data and int(data["schema_version"]) != 2:
            raise ValueError("지원하지 않는 제스처 템플릿 버전입니다")
        for key in result:
            if key in data:
                result[key] = np.array(data[key])
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
    np.savez_compressed(out, schema_version=np.array(2), **data)
    return out.getvalue()


class CustomGestureStore:
    """Read legacy NPZ and version 2 templates without mixing feature dimensions."""
    def __init__(self, path):
        from pathlib import Path
        self.legacy = CustomGestures(path)
        self.data = read_templates(Path(path).read_bytes()) if Path(path).exists() else empty_templates()
        self.history = deque(maxlen=1000)
        self.latched = False
        self.latched_name = None
        self.missing_since = None

    @property
    def n(self):
        return self.legacy.n + len(self.data["sequences"])

    def class_names(self):
        return sorted(set(self.legacy.class_names()) | set(self.data["sequence_names"]))

    def nearest_class(self, feats):
        return self.legacy.nearest_class(feats)

    def classify_with_distance(self, landmarks):
        return self.legacy.classify_with_distance(landmarks)

    def sequence_comparisons(self, sequence, motion, count):
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
            details = (motion_comparison(sequence, reference, count) if motion == 'DYNAMIC'
                       else dict(score=matching_distance(sequence, reference, count)))
            candidates.append(dict(template_index=index, name=str(name), **details))
        return sorted(candidates, key=lambda item: item['score'])

    def nearest_sequence(self, sequence, motion, count):
        candidates = self.sequence_comparisons(sequence, motion, count)
        return ((candidates[0]['score'], candidates[0]['name']) if candidates
                else (float('inf'), None))

    def reset_motion(self):
        self.history.clear()
        self.latched = False
        self.latched_name = None
        self.missing_since = None

    def update(self, hands, now, disabled=()):
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
        if points is None:
            self.history.clear()
            if self.missing_since is None:
                self.missing_since = now
            if now - self.missing_since >= 0.3:
                self.latched = False
            return None, None, self.latched, None
        self.missing_since = None
        if self.latched:
            return None, None, True, None
        identity = tuple(sorted(h.get("handedness", "Unknown") for h in hands))
        if self.history and (now - self.history[-1][0] > 0.25 or now <= self.history[-1][0]
                             or identity != self.history[-1][2]):
            self.history.clear()
        if not self.history or now - self.history[-1][0] >= 0.05:
            self.history.append((now, points, identity))
        count = len(points)
        best_static, best_dynamic = (MATCH_DISTANCE, None), (MATCH_DISTANCE, None)
        pending_motion = False
        for seq, name, motion, n, duration in zip(*(self.data[k] for k in EXTRA_KEYS)):
            if count != n or name in disabled:
                continue
            if motion == "STATIC":
                current = encode_sequence([0, 1], [points, points])
                score = matching_distance(current, seq, count)
                if score < best_static[0]:
                    best_static = score, str(name)
                continue
            for speed in (0.7, 1.0, 1.3):
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
                        current_prefix = encode_sequence([v[0] for v in prefix_window],
                                                         [v[1] for v in prefix_window])
                        movement = distance(current_prefix, np.repeat(current_prefix[:1], FRAMES, axis=0), count)
                        expected = prefix_sequence(seq, min(1.0, elapsed / span))
                        if movement >= PREFIX_MIN_MOTION and motion_matching_distance(current_prefix, expected, count) < PREFIX_DISTANCE:
                            pending_motion = True
                            break
                window = [item for item in self.history if item[0] >= now - span - 0.04]
                if len(window) < 6 or window[-1][0] - window[0][0] < span * 0.9:
                    continue
                current = encode_sequence([v[0] for v in window], [v[1] for v in window])
                score = motion_matching_distance(current, seq, count)
                if score < best_dynamic[0]:
                    best_dynamic = score, str(name)
        if best_dynamic[1]:
            self.latched = True
            self.latched_name = best_dynamic[1]
            self.history.clear()
            return None, best_dynamic[1], True, best_dynamic[0]
        if pending_motion:
            return None, None, True, None
        return best_static[1], None, bool(best_static[1]), (best_static[0] if best_static[1] else None)
