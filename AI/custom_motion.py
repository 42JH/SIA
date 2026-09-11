"""Versioned custom gesture templates: legacy poses and timed one/two-hand takes.

Coordinates retain orientation and relative hand placement. Only the initial
common translation and palm scale are removed; per-frame normalization would
erase the motion we want to recognize.
"""
import io
from collections import deque

import numpy as np

from hands import CustomGestures

FRAMES = 24
MATCH_DISTANCE = 0.22  # RMS landmark error, in initial palm lengths
PREFIX_DISTANCE = 0.16
PREFIX_MIN_MOTION = 0.08
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


def encode_sequence(times, points):
    times, points = np.asarray(times), np.asarray(points, dtype=np.float32)
    if len(times) < 2 or np.any(np.diff(times) <= 0):
        raise ValueError("촬영 시각이 올바르지 않습니다")
    origin = points[0, :, 0].mean(axis=0)
    scale = np.linalg.norm(points[0, :, 9] - points[0, :, 0], axis=-1).mean()
    normalized = (points - origin) / max(float(scale), 1e-6)
    flat = normalized.reshape(len(times), -1)
    grid = np.linspace(times[0], times[-1], FRAMES)
    sampled = np.stack([np.interp(grid, times, col) for col in flat.T], axis=-1)
    result = np.zeros((FRAMES, 2, 21, 2), np.float32)
    result[:, :points.shape[1]] = sampled.reshape(FRAMES, points.shape[1], 21, 2)
    return result


def distance(a, b, count):
    return float(np.sqrt(np.mean(np.sum((a[:, :count] - b[:, :count]) ** 2, axis=-1))))


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

    def nearest_sequence(self, sequence, motion, count):
        candidates = [(distance(sequence, s, count), str(name))
                      for s, name, m, h in zip(*(self.data[k] for k in EXTRA_KEYS[:4]))
                      if m == motion and h == count]
        return min(candidates, default=(float("inf"), None))

    def reset_motion(self):
        self.history.clear()
        self.latched = False
        self.latched_name = None
        self.missing_since = None

    def update(self, hands, now, disabled=()):
        """Return (held two-hand pose, completed motion, suppress other commands).

        Motion fires once, then requires hands to leave for 0.3 s before rearming.
        Missing/ambiguous hands and long camera gaps cannot bridge a trajectory.
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
            return None, None, self.latched
        self.missing_since = None
        if self.latched:
            return None, None, True
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
                score = distance(current, seq, count)
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
                        if movement >= PREFIX_MIN_MOTION and distance(current_prefix, expected, count) < PREFIX_DISTANCE:
                            pending_motion = True
                            break
                window = [item for item in self.history if item[0] >= now - span - 0.04]
                if len(window) < 6 or window[-1][0] - window[0][0] < span * 0.9:
                    continue
                current = encode_sequence([v[0] for v in window], [v[1] for v in window])
                score = distance(current, seq, count)
                if score < best_dynamic[0]:
                    best_dynamic = score, str(name)
        if best_dynamic[1]:
            self.latched = True
            self.latched_name = best_dynamic[1]
            self.history.clear()
            return None, best_dynamic[1], True
        if pending_motion:
            return None, None, True
        return best_static[1], None, bool(best_static[1])
