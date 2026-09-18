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

FRAMES = 24
MATCH_DISTANCE = 0.22  # RMS landmark error, in initial palm lengths
PREFIX_DISTANCE = 0.16
PREFIX_MIN_MOTION = 0.08
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
        self._last_claimed = False  # 가장 최근 정상 프레임의 claimed — 찰나의 추적 실패를 이어붙이는 데 쓴다

    @property
    def n(self):
        return self.legacy.n + len(self.data["sequences"])

    def class_names(self):
        return sorted(set(self.legacy.class_names()) | set(self.data["sequence_names"]))

    def nearest_class(self, feats):
        return self.legacy.nearest_class(feats)

    def classify_with_distance(self, landmarks, disabled=()):
        return self.legacy.classify_with_distance(landmarks, disabled=disabled)

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
        self.latched = False
        self.latched_name = None
        self.missing_since = None
        self._last_claimed = False

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
        # 양손 후보를 추적하던 중 한 손만 검출되면 새 한손 동작으로 섞지 않는다.
        two_hand_gap = (len(hands) == 1 and self.history
                        and len(self.history[-1][1]) == 2
                        and any(n == 2 and name not in disabled for n, name in
                                zip(self.data['hand_counts'], self.data['sequence_names'])))
        if two_hand_gap:
            points = None
        if points is None:
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
            if elapsed >= 0.3:
                self.latched = False
            claimed = self.latched or (elapsed < TRACKING_GRACE_S and had_progress)
            return None, None, claimed, None
        if self.missing_since is not None and now - self.missing_since >= TRACKING_GRACE_S:
            self.history.clear()
            self._last_claimed = False
        self.missing_since = None
        if self.latched:
            self._last_claimed = True
            return None, None, True, None
        identity = hand_identity(hands)
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
            self._last_claimed = True
            return None, best_dynamic[1], True, best_dynamic[0]
        if pending_motion:
            self._last_claimed = True
            return None, None, True, None
        self._last_claimed = bool(best_static[1])
        return best_static[1], None, self._last_claimed, (best_static[0] if best_static[1] else None)
