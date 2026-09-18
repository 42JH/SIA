"""내장 브이/검지 분류를 3D 관절 형태로 검증한다.

분류기 출력은 손의 방향에 따라 틀릴 수 있다. 이미지의 x/y 대소 비교 대신
world 좌표의 관절 굽힘과 손목으로부터의 뻗음을 사용해 좌우/회전에 독립적으로
검증한다. 모델이 놓친 브이는 뚜렷한 벌어짐까지 확인한 경우에만 복구한다.
"""
import numpy as np


POINTING = 'Pointing_Up'
VICTORY = 'Victory'
FIST = 'Closed_Fist'
PALM = 'Open_Palm'
# 손목~엄지끝 거리(손바닥 길이 단위). 실제 주먹 사진은 1.1~1.2, 엄지척/전화
# 등 엄지를 뻗는 동작은 1.6 이상이었다 — 그 사이 여유를 두고 잡은 값이다.
FIST_THUMB_REACH_MAX = 1.4
# 엄지끝~검지끝 거리(손바닥 길이 단위). 손바닥 펴기(실측 0.63~0.80)는 엄지가
# 옆으로 벌어져 검지에 비교적 가깝지만, '네 손가락'처럼 엄지를 손목 쪽으로
# 접어 넣은 동작(실측 1.05)은 이보다 뚜렷이 멀다 — 네 손가락 모두 편 것만으로
# 손바닥 펴기로 단정하지 않기 위한 여유값이다.
OPEN_PALM_THUMB_SPAN_MAX = 0.9


def verified_finger_gesture(label, world_landmarks):
    """(사용할 라벨, 판정 근거)를 반환. 불명확/모순된 후보는 None으로 보류.

    수치는 보정된 확률이 아닌 보수적인 기하 조건이다. extended/folded 사이에
    빈 구간을 둬 부분 굽힘·가림을 다른 동작으로 강제 분류하지 않는다.
    """
    fallback = label in (None, 'None')
    if label not in (POINTING, VICTORY, 'Thumb_Up', 'Thumb_Down', FIST, PALM, None, 'None'):
        return label, 'model'
    abstain = (label, 'model') if fallback else ('None', 'unverified_finger_pose')
    try:
        points = np.asarray(world_landmarks, dtype=float)
    except (TypeError, ValueError):
        return abstain
    if points.shape != (21, 3) or not np.isfinite(points).all():
        return abstain
    palm = float(np.linalg.norm(points[9] - points[0]))
    if palm < 1e-6:
        return abstain

    states = []
    for mcp in (5, 9, 13, 17):
        finger = points[mcp:mcp + 4]
        bones = np.diff(finger, axis=0)
        lengths = np.linalg.norm(bones, axis=1)
        if np.min(lengths) < palm * 0.03:
            return abstain
        straightness = float(np.linalg.norm(finger[3] - finger[0]) / lengths.sum())
        reach = float((np.linalg.norm(finger[3] - points[0])
                       - np.linalg.norm(finger[1] - points[0])) / palm)
        cosines = np.sum(bones[:-1] * bones[1:], axis=1) / (lengths[:-1] * lengths[1:])
        if straightness >= 0.90 and reach >= 0.20 and np.min(cosines) >= 0.65:
            states.append('extended')
        elif straightness <= 0.90 and reach <= 0.05:
            states.append('folded')
        else:
            states.append('uncertain')

    index, middle, ring, pinkie = states
    thumb_reach = float(np.linalg.norm(points[4] - points[0]) / palm)
    thumb_span = float(np.linalg.norm(points[4] - points[8]) / palm)
    if label in ('Thumb_Up', 'Thumb_Down'):
        # 엄지+새끼손가락(전화) 등을 엄지 하나만 편 기본 동작으로 거절하지 않는다.
        if 'extended' in states:
            return 'None', 'incompatible_finger_pose'
        if 'uncertain' in states:
            return label, 'model'
        return label, 'verified_finger_pose'
    if label == FIST:
        # 네 손가락이 뚜렷이 접혀 있어야 하고, 엄지도 손목 가까이 접혀 있어야
        # 한다 — 엄지척·전화처럼 엄지만 뻗은 동작과 겹치지 않게 한다.
        if 'uncertain' in states:
            return abstain
        if states != ['folded', 'folded', 'folded', 'folded'] or thumb_reach > FIST_THUMB_REACH_MAX:
            return 'None', 'incompatible_finger_pose'
        return label, 'verified_finger_pose'
    if label == PALM:
        # 네 손가락이 뚜렷이 펴져 있어야 하고, 엄지도 검지에서 너무 멀지 않게
        # 벌어져 있어야 한다 — '네 손가락'처럼 엄지만 접어 넣은 동작과
        # 겹치지 않게 한다.
        if 'uncertain' in states:
            return abstain
        if states != ['extended', 'extended', 'extended', 'extended'] or thumb_span > OPEN_PALM_THUMB_SPAN_MAX:
            return 'None', 'incompatible_finger_pose'
        return label, 'verified_finger_pose'
    if fallback:
        if states == ['folded', 'folded', 'folded', 'folded'] and thumb_reach <= FIST_THUMB_REACH_MAX:
            return FIST, 'corrected_finger_pose'
        if states == ['extended', 'extended', 'extended', 'extended'] and thumb_span <= OPEN_PALM_THUMB_SPAN_MAX:
            return PALM, 'corrected_finger_pose'
        if states != ['extended', 'extended', 'folded', 'folded']:
            return label, 'model'
        a, b = points[8] - points[5], points[12] - points[9]
        divergence = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
        # None 복구는 교정보다 엄격하다: 손끝 간격 0.45 손바닥 이상,
        # 두 손가락 방향 약 15도 이상. 붙인 두 손가락은 커스텀으로 남긴다.
        if np.linalg.norm(points[8] - points[12]) / palm < 0.45 or divergence > 0.966:
            return label, 'model'
    if 'uncertain' in (index, ring, pinkie):
        return abstain
    if index != 'extended' or ring != 'folded' or pinkie != 'folded':
        return 'None', 'incompatible_finger_pose'
    if middle == 'folded':
        candidate = POINTING
    elif middle == 'extended':
        # 붙인 두 손가락은 브이와 별개 커스텀 모양일 수 있다.
        separation = float(np.linalg.norm(points[8] - points[12]) / palm)
        if separation < 0.35:
            return 'None', 'incompatible_finger_pose'
        candidate = VICTORY
    else:
        return abstain

    if candidate == VICTORY or candidate != label:
        # 브이는 엄지를 편 세 손가락 모양과 구분한다. 다른 동작으로 교정할
        # 때도 엄지까지 확인하며, 애매하면 분류를 보류한다.
        a, b = points[3] - points[2], points[4] - points[3]
        denominator = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denominator < palm * palm * 0.0009:
            return abstain
        if float(np.dot(a, b) / denominator) > 0.95:
            return (label, 'model') if fallback else ('None', 'incompatible_finger_pose')
    if candidate != label:
        return candidate, 'corrected_finger_pose'
    return label, 'verified_finger_pose'
